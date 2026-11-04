"""M2 fixed current-water query; no Knowledge/history/event or write surface."""
from apps.monitoring.contracts import METRICS
from apps.ai_service.business_tools.current_water_quality import project_water_tool

HELP = ('鳗鲡养殖智能体：/当前水质、查询当前水质、查询水质是直接只读查询，不调用模型。'
        '\n其他自然语言仅在本次 AI 授权有效时调用模型；不支持切换设备或写操作。')


def is_current_query(text):
    """Exact no-argument aliases only; no fuzzy matching or device extraction."""
    return text.strip().rstrip('。.!！?？') in ('查询当前水质', '查询水质')

def plain(value, limit=350):
    text = ''.join(c for c in str(value).replace('@', '＠') if c.isprintable() or c == '\n')
    return text[:limit] + ('…' if len(text) > limit else '')

def _time(value):
    return plain(value or '无观测时间', 64)

class ReadOnlyQueries:
    def __init__(self, monitoring, knowledge=None, *, live=False, instance_id=None):
        if knowledge is not None:
            from .contracts import BotError
            raise BotError('M2_KNOWLEDGE_DISABLED')
        self._capture = monitoring.capture_water if monitoring is not None else None
        self._instance_id = instance_id

    def execute(self, message, access):
        content = '/当前水质' if is_current_query(message.content) else message.content
        pieces = content.lstrip('/').split(maxsplit=1)
        command, argument = pieces[0], pieces[1] if len(pieces) == 2 else ''
        if command.lower() in ('help','帮助') and not argument:
            return 'OK', HELP
        if command in ('AI','问AI'):
            return 'AI_DISABLED', 'AI 默认关闭；M2 仅支持独立离线验收。'
        if command != '当前水质':
            return 'UNSUPPORTED_COMMAND', '仅支持 /当前水质 和 /帮助。'
        if 'current' not in access.capabilities:
            return 'CAPABILITY_DENIED', '此群未获准当前水质查询。'
        if argument:
            return 'INVALID_ARGUMENTS', '实例和设备由本机配置固定，命令不接受参数。'
        return 'OK', self.current(access.device_id)

    def current(self, device):
        capture = self._capture(device)
        facts = project_water_tool(capture)
        dq = facts['data_quality']
        lines = [f'当前水质 · {device} · {facts["source_kind"].upper()}',
                 f'观测：{_time(facts.get("water_quality", {}).get("observed_at") if facts["water_quality"] else None)}',
                 f'质量 {dq["quality"]} / 新鲜度 {dq["freshness"]} / 连接 {dq["connectivity"]}']
        for metric in capture.metrics:
            label = METRICS[metric.id][0]
            value = metric.mean if metric.quality == 'valid' else '数据不足'
            lines.append(f'{label}：{value} {metric.unit}（{metric.quality}）')
        lines.extend(plain(f['message']) for f in facts.get('findings', []) if f['state'] == 'HIT')
        lines.append('查询不等于重新采样；过期/缺测不能认定当前正常。')
        if self._instance_id:
            lines.insert(0, '只读实例：'+self._instance_id)
        return '\n'.join(lines)

