"""Capture synthetic event-scope A/B requests through the official Web runtime."""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tests.support import FakeSDK, sdk_final, sdk_tool
from apps.ai_service.active_event_execution import ACTIVE_EVENT_TOOL_NAMES, ActiveEventTrialConfig
from apps.ai_service.business_tools.active_events import ACTIVE_EVENTS, RESULT_INSTRUCTION, result_metadata
from apps.ai_service.execution import load_execution_config
from apps.ai_service.normal_selection import load_unified_tool_trials
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.streaming import load_streaming_config
from apps.knowledge.tests.support import reference_knowledge
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from scripts.dev.check_qq_agent import _new_directory, _private


PROFILE = assistant_profile('dashscope-qwen38-flash-r1')
NOW = datetime(2026, 11, 22, 7, 20, tzinfo=timezone.utc)
POND = 'scope-sim-pond'
BOARD = 'scope-board'
QUESTION = '当前发生了什么事件？'
PREVIOUS_GUIDANCE = (
    '按设备分开报告事件，区分 simulator 模拟记录和 device_report 设备报告。'
    '将 ACTIVE、INDETERMINATE、NEEDS_REVIEW 分别解释为活动、待核实、待复核。只把 ACTIVE 计入活动风险。'
    '依据 last_observed_at 和各来源的观测时间与新鲜度说明缺测和过期，evaluated_at 是评估时间。'
    'NO_MATCH 表示本次查询范围内无符合条件的事件，NO_DATA 表示该范围无观测。零条活动风险无法证明健康或风险已消退。'
    'omitted_count 大于零时说明结果已截断。设备报告中断仅描述报告更新，无法据此判断设备离线。'
    'abnormal_video_count 是被模型标为异常的视频数量，result_timestamp 是行为结果版本时间。'
    '如问到行为上报时间，说明本次事件结果未提供。'
    '外观与行为信号需人工核查，仅凭这些信号无法确诊疾病。'
    '这次查询只读事件信息，确认、删除、结束事件或操作设备均需另行处理。'
)
CASES = {
    'water_fresh_board_missing': ('NO_MATCH', ('ASSESSED', 'MISSING', 'MISSING'),
        '只在本轮有有效观测的模拟水质范围内说无匹配。模拟视觉缺测，且板端缺报告，暂无法核实各自的视觉相关情况。'),
    'water_fresh_board_stale': ('NO_MATCH', ('ASSESSED', 'MISSING', 'STALE'),
        '模拟水质无匹配，模拟视觉缺测，板端旧报告已过期，无法核实当前外观和行为。报告过期不能证明设备离线。'),
    'water_fresh_board_report_only': ('NO_MATCH', ('ASSESSED', 'MISSING', 'REPORT_ONLY'),
        '模拟水质无匹配，模拟视觉缺测。板端已有较新报告，外观和行为的完整覆盖仍未知。'),
    'all_missing': ('NO_DATA', ('MISSING', 'MISSING', 'MISSING'),
        '首句说明当前事件缺少观测而无法核实，禁止将没有证据写成没有事件。'),
    'water_risk_and_board_signal': ('OK', ('ASSESSED', 'MISSING', 'REPORT_ONLY'),
        '按实际来源报告模拟水质风险与板端外观模型标记。交代证据和时间，不能诊断疾病或说其他视觉均正常。'),
}


def synthetic_report(at, *, positive=False):
    labels = [dict(label='ascites', name='腹水', targets=2, count=2, avg_confidence=.8,
                   last_bbox=[0, 0, 10, 10])] if positive else []
    return dict(schema_version=1, report_id='scope-board-report', device_id=BOARD, sent_at=at.isoformat(),
                window=dict(start=(at - timedelta(seconds=60)).isoformat(), end=at.isoformat(),
                            duration_s=60, frames_processed=50),
                has_abnormality=positive, report_text='合成报告',
                detection=dict(unique_tracks=8, avg_per_frame=3, max_per_frame=4, avg_confidence=.8),
                abnormalities=labels, measurement=None,
                behavior=dict(report_context=dict(aggregation_policy='peak_frame_v1',
                    observed_detection_frames=50, observed_abnormality_frames=2 if positive else 0,
                    abnormality_count_semantics='detections_in_one_peak_frame',
                    abnormality_status='observed' if positive else 'not_observed')))


def fixture(directory, case):
    repository = MonitoringRepository(directory / 'monitoring.sqlite3')
    service = MonitoringService(repository, device_names={POND: '合成模拟池'}, clock=lambda: NOW)
    positive = case == 'water_risk_and_board_signal'
    if case != 'all_missing':
        simulator = Simulator(device_id=POND, session_id='scope-review', mode='water-only',
                              start=NOW - timedelta(seconds=10))
        batch = simulator.advance()
        if positive:
            batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=4.2, min=4.2, max=4.2, latest=4.2)
        service.ingest(batch)
    if case in ('water_fresh_board_stale', 'water_fresh_board_report_only', 'water_risk_and_board_signal'):
        at = NOW - timedelta(seconds=121) if case == 'water_fresh_board_stale' else NOW
        repository.import_device_report(synthetic_report(at, positive=positive), received_at=at, inbox_cursor=1, now=at)
    return service


def capture(directory, case):
    monitoring = fixture(directory, case)
    scripted_text = ('模拟水质有溶解氧偏低风险，板端报告有外观异常信号待人工核查。'
                     if case == 'water_risk_and_board_signal' else '当前没有任何异常。')
    sdk = FakeSDK([sdk_tool(ACTIVE_EVENTS, 'event-scope', '{}', PROFILE.model),
                   sdk_final(scripted_text, model=PROFILE.model)], model=PROFILE.model)
    assistant = ManagementAssistant(ManagementAssistantService(monitoring, knowledge=reference_knowledge(),
        credentials=CredentialStore(process_env={PROFILE.credential_ref: 'synthetic-event-scope-key'}),
        traces=JsonlTraceSink(directory / 'trace.jsonl', tool_names=ACTIVE_EVENT_TOOL_NAMES),
        policy_directory=directory / 'policy', active_event_config=ActiveEventTrialConfig(enabled=True, device_report_device_id=BOARD),
        execution_config=load_execution_config(enable_trial=True), streaming_config=load_streaming_config(enable_trial=True),
        unified_config=load_unified_tool_trials(normal=True, streaming=True),
        gateway_factory=lambda: OpenAICompatibleAdapter(async_client_factory=sdk.factory)))
    with create_app(data_service=monitoring, ai=assistant).test_client() as client:
        headers = {'X-Management-AI': assistant.browser_token}
        policy = client.get('/api/ai/tool-policy').get_json()
        saved = client.post('/api/ai/tool-policy', headers=headers, json={
            'epoch': policy['epoch'], 'revision': policy['revision'], 'selected_tools': [ACTIVE_EVENTS]})
        if saved.status_code != 200:
            raise ValueError('EVENT_SCOPE_POLICY_SETUP_FAILED')
        boot = client.get(f'/api/ai/bootstrap?device={POND}').get_json()
        preset = next(row for row in boot['presets'] if row['preset_id'] == PROFILE.preset_id)
        control = client.post('/api/ai/requests', headers=headers, json={'epoch': boot['epoch']}).get_json()
        response = client.post('/api/ai/messages', headers=headers, json=dict(preset_id=PROFILE.preset_id,
            device_id=POND, question=QUESTION, history=[], epoch=boot['epoch'],
            revision=preset['execution']['revision'], confirm_network=True, **control))
        result = response.get_json()['result']
    if len(sdk.bodies) != 2 or not result['successful_turn'] or not all(client.closed for client in sdk.clients):
        raise ValueError('EVENT_SCOPE_CAPTURE_INCOMPLETE')
    return sdk.bodies, result['final_text'], scripted_text


def replay_pair(captured):
    candidate = deepcopy(captured)
    candidate['tool_choice'] = 'none'
    system = candidate['messages'][0]
    if system['role'] != 'system' or not system['content'].endswith(RESULT_INSTRUCTION):
        raise ValueError('EVENT_SCOPE_OFFICIAL_GUIDANCE_MISMATCH')
    previous = deepcopy(candidate)
    previous['messages'][0]['content'] = system['content'].removesuffix(RESULT_INSTRUCTION) + PREVIOUS_GUIDANCE
    return {'A': previous, 'B': candidate}


def run(output):
    out = _new_directory(output)
    rows = {}
    for case, (status, states, rubric) in CASES.items():
        with TemporaryDirectory(prefix=f'{case}-', dir=out) as temporary:
            (first, final), reply, scripted_text = capture(Path(temporary), case)
        tool_message = final['messages'][-1]
        payload = json.loads(tool_message['content'])
        if (tool_message['role'] != 'tool' or not result_metadata(payload) or payload['status'] != status
                or tuple(row['state'] for row in payload['observation_scope']) != states
                or (status == 'OK') != (reply == scripted_text)
                or (status == 'OK' and {row['source_kind'] for row in payload['items']} != {'simulator', 'device_report'})):
            raise ValueError(f'EVENT_SCOPE_ORACLE_MISMATCH: {case}')
        rows[case] = dict(expected_status=status, expected_states=states, rubric=rubric,
                          first_request=first, replay_requests=replay_pair(final), tool_result=payload,
                          scripted_model_reply=scripted_text, published_reply=reply)
    report = out / 'result.json'
    _private(report, {'mode': 'synthetic_offline_capture', 'requests_sent': 0, 'cases': rows})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='A new directory beneath repository outputs/')
    print(run(parser.parse_args().output))


if __name__ == '__main__':
    main()
