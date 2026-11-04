"""Finite local Qwen regression; synthetic instance only, never constructs QQ I/O."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

QUESTIONS = ('现在鱼塘水质怎么样？', '当前溶解氧是多少？', 'pH 数据可靠吗？',
             '设备现在在线吗？', '有没有低氧风险？', '什么是溶解氧？')


def execute_batch(request, directory, questions, *, factory=None):
    from apps.qq_bot.management_run import ManagementRun
    from apps.qq_bot.ai_coordinator import QQAICoordinator
    from apps.qq_bot.intent import GatewayMention
    from apps.qq_bot.trial_configuration import write_new
    host = ManagementRun(request, directory, async_client_factory=factory)
    rows = []; stop_code = 'BATCH_COMPLETED'
    # Caller is a trusted local command after explicit operator approval. These
    # synthetic inputs are never presented as authenticated QQ deliveries.
    try:
        host.approve(host.plan(), confirmed=True)
        coordinator = QQAICoordinator(host.access, host.monitoring, host.base_service,
            config=host.config, conversations=host.store, session_run=host)
        owner = object(); coordinator._mention_owner = owner
        for index, question in enumerate(questions, 1):
            plan = None; started = time.monotonic()
            row = dict(case=index, backend_completed=False, contract_valid=False,
                       qq_submissions=0, history_committed=False)
            try:
                host.check()
                message_id = 'local-case-'+str(index)
                raw = json.dumps(dict(op=0, t='GROUP_AT_MESSAGE_CREATE', d=dict(
                    id=message_id, group_openid=request.inputs.group_id,
                    author=dict(member_openid=request.members[(index-1)//6], bot=False),
                    timestamp=datetime.now(timezone.utc).isoformat(), content='/问AI '+question))).encode()
                proof = GatewayMention(owner, host.access.app_id, message_id, hashlib.sha256(raw).hexdigest())
                plan = coordinator.prepare(raw, transport_app_id=host.access.app_id, mention=proof,
                    capacity_check=lambda _: None)  # Synchronous single-flight local experiment.
                result = coordinator.execute(plan)
                row.update(code=result.error_code or 'OK', backend_completed=result.completed,
                    branch=result.branch, model_requests=result.model_requests,
                    tool_executions=result.tool_executions)
                if result.completed:
                    coordinator.validate_delivery_candidate(plan, result)
                    row['publication_code'] = result.publication.code
                    row['safe_fallback'] = result.publication.facts_only
                    row['contract_valid'] = bool(result.publication.allowed and not result.publication.facts_only)
                plan.handle.assert_resources_closed()
            except KeyboardInterrupt:
                stop_code = 'BATCH_INTERRUPTED'; row['code'] = stop_code
                if plan: plan.handle.cancel()
            except Exception as error:
                code = getattr(error, 'code', 'BATCH_EXECUTION_FAILED')
                row['code'] = code if isinstance(code, str) and code.isascii() and code.replace('_','').isalnum() else 'BATCH_EXECUTION_FAILED'
                stop_code = 'BATCH_FAILED_STOP'
            finally:
                row['seconds'] = round(time.monotonic()-started, 3)
                if plan:
                    coordinator.discard(plan, outcome=dict(state='LOCAL_REVIEWED', code=row['code'],
                        api_accepted=False, history_code='NO_QQ_DELIVERY'))
                rows.append(row)
                write_new(directory/f'case-{index}.json', row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            if not row['contract_valid']:
                stop_code = 'BATCH_FAILED_STOP' if stop_code == 'BATCH_COMPLETED' else stop_code
            if stop_code != 'BATCH_COMPLETED': break
            try: host.check()
            except Exception:
                stop_code = 'BATCH_SAFETY_STOP'; break
    finally:
        host.close()
        report = host.report(stop_code)
        report.update(cases=rows, qq_network_requests=0, automatic_retry=False,
                      purpose='LOCAL_PROVIDER_SYNTHETIC_REVIEW_NOT_QQ_ACCEPTANCE')
        write_new(directory/'result.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='本机 Qwen 有限批次检查；不连接 QQ')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--cases', type=int, default=6, choices=range(1,21))
    args = parser.parse_args(argv)
    from apps.qq_bot.management_config import PREPARATION, load_request
    from apps.ai_service.channel_management_live import prepared_scope, preparation_record
    from apps.qq_bot.conversations import ConversationOptions
    from apps.qq_bot.trial_configuration import read_json, write_new
    from apps.ai_service.management_channel_budget import reservation_per_turn
    scope = prepared_scope(ConversationOptions(trigger_mode='mention_ai', memory_enabled=True))
    if read_json(PREPARATION) != preparation_record(scope):
        raise SystemExit('MANAGEMENT_SCOPE_REVIEW_REQUIRED')
    budget = reservation_per_turn()*args.cases
    summary = dict(code='PROVIDER_BATCH_CHECKED', cases=args.cases, max_http_requests=args.cases*2,
        reserved_budget_cny=str(budget), output_tokens_per_request=2048, seconds_per_turn=90,
        provider='dashscope', model='qwen3.8-flash', preset='dashscope-qwen38-flash-r1',
        retries=0, qq_network_requests=0, source='NEW_SYNTHETIC_SIMULATOR',
        scope_sha256=preparation_record(scope)['scope_sha256'])
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not args.run: return 0
    digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:12]
    print('仅请求 Qwen，使用新建模拟数据，不连接 QQ。预算是保守预留，不是云账单上限。', flush=True)
    if input('批准请输入 APPROVE QWEN '+digest+'：').strip() != 'APPROVE QWEN '+digest:
        raise SystemExit('PROVIDER_BATCH_DECLINED')
    # Credentials resolve only via the same protected store as Web/Bot, after approval.
    from apps.ai_backend.credentials import CredentialStore
    from apps.ai_service.runtime.locations import private_project_location
    from apps.ai_service.runtime.assistant import assistant_profile
    from apps.ai_service.channel_trial import PRESET
    try:
        location = private_project_location(ROOT)
        status = CredentialStore(location.env_path, private_location=location).status(assistant_profile(PRESET).credential_ref)
        if status.availability != 'PRESENT': raise ValueError()
    except Exception:
        raise SystemExit('PROVIDER_CREDENTIAL_UNAVAILABLE_NO_REQUESTS') from None
    import logging
    for name in ('openai','httpx','httpcore'): logging.getLogger(name).disabled = True
    from apps.qq_bot.management_cli import initialize_demo
    parent = ROOT/'outputs/provider-checks'; parent.mkdir(exist_ok=True, parents=True)
    root = parent/('batch-'+uuid.uuid4().hex); root.mkdir()
    path = initialize_demo(root/'instance', root/'config', app_id='123456789',
        group_id='local-provider-check', members=tuple('local-member-'+str(i) for i in range(4)), enable=True)
    value = read_json(path)
    value['limits'] = dict(max_turns=args.cases, seconds=7200, total_budget_cny=str(budget))
    selected = root/'request.json'; write_new(selected, value)
    request = load_request(selected); directory=root/'run'; directory.mkdir()
    report = execute_batch(request, directory, [QUESTIONS[i % len(QUESTIONS)] for i in range(args.cases)])
    print(json.dumps(dict(code=report['code'], result_file=str(directory/'result.json'),
        passed=sum(row['contract_valid'] for row in report['cases']), cases=len(report['cases'])), ensure_ascii=False))
    return 0 if len(report['cases'])==args.cases and all(r['contract_valid'] for r in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
