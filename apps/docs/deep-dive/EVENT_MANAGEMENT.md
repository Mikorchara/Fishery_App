# 事件族、状态文案、时间筛选与历史清理

本项目选择性同步 Prototype 的 EVT-1/EVT-2 和文案收尾，保留独立启动器、品牌、业务数据路径及原 AI 权限。来源提交：72795a1、70c4260、1d9d87d；运行不依赖 Prototype。

## 等级关联与显示

同设备、通道、指标、风险方向、规则身份的水质等级组成事件族。低氧三级同族，温度/pH 的偏高和偏低分别管理；视觉 code 和不同设备不合并。各 code 保留事件 ID、首末观测、状态和批次，等级变化不是恢复证明。

risk_family 通过原入库事务保存周期身份及等级变化证据，保留首次和最近 99 次变化，公开 omitted_transitions。消退后复发形成新周期。旧记录只读保守关联，不伪造缺失历史。

首页优先展示当前有可靠依据的等级；没有可靠当前等级时显示一个“当前等级未知”的族提示，不把历史最高等级冒充当前结论。事件列表和详情仍保留各等级记录。

| 显示条件 | 文案 |
|---|---|
| 原等级 INDETERMINATE、OTHER_RISK_CONDITION_ACTIVE，当前可靠等级更高且为严重/极低氧 | 已升级为严重低氧／已升级为极低氧 |
| 其他等级转换或升级方向证据不足 | 同指标等级已变化 |
| INDETERMINATE，当前明确 offline 或新报文缺失视觉通道 | 监测数据中断 |
| 其他 INDETERMINATE，包括仅过期但在线、无效、不完整、规则变化和旧记录 | 恢复状态待确认 |
| ACTIVE 且视觉恢复 CLEAR 计数为 1/2 | 恢复观察中 1/3、2/3 |
| 其他 ACTIVE | 异常持续 |
| RESOLVED | 规则条件已消退 |

首页、列表、详情及关联成员共用 eventStateName；详情通过 eventStateReasonName 解释原因，保留原因代码。历史 continuity=interrupted 仅说明过去存在不连续，不单独证明当前离线。SIMULATOR 来源和非疾病确诊说明始终保留。

current_data_quality 和 family_level_change 仅为读取投影，不落盘；它们不改变原始证据、时间、code、诊断阈值或状态机。没有 Schema 迁移，user_version 仍为 1。[视觉三窗恢复](EVENT_LIFECYCLE.md)继续有效。

## 历史查询

GET /api/events 支持 lookback_minutes=5/10/30/60/all（默认 all），q、severity、status 可组合；limit 默认 50、最大 100，offset 默认 0。

范围按事件关注区间相交计算：occurred_at 到 resolved_at；未结束事件保持开放关注区间，所以早先发生的活动或未知事件仍可出现在最近五分钟。未知期间不等于持续检出。旧 closed 记录缺少可靠结束时间时仅在全部记录展示。

对完整留存集合先筛选再分页，不仅过滤首页最近几条。“全部记录”不包含已经裁剪或删除的数据。

## 硬删除保护

只有 RESOLVED + closed、具有有效恢复时间、无 alerts 关联且未被其他事件 superseded_by 引用的记录可删除。ACTIVE、恢复观察、未知和恢复证据不明的旧记录均不可删除。

- 单条删除：一次确认。
- 清理全部已结束事件：预览与最终确认两步，展示服务端预计数量。
- 批量范围：全部设备、全部时间的可删除记录，忽略当前筛选和分页。
- 取消不提交；硬删除没有应用内撤销功能。

POST /api/events/deletion-preview 只预览；POST /api/events/delete 提交同一 scope/event_id/revision。要求回环来源、允许 Host/Origin、JSON 和当前进程生成的 X-Management-Events 能力令牌。该令牌不是用户身份认证，不向 AI Tool 开放写能力。

提交在 BEGIN IMMEDIATE 内重新核对状态、alerts/superseded_by 引用和候选原 payload revision；并发变化返回冲突，不自动重试。只删除 events，不删除水质 history、batches、current、Knowledge、Settings、Policy 或 Trace。事件族快照保留历史标识与证据；关联成员列表只列仍存在的记录。

人工 ACK/Close/Snooze、操作审计和长期归档尚未实现。后续加入人工操作记录时，必须同时调整手动删除与自动留存保护。

## 实现与验收入口

monitoring/events.py：状态迁移与只读质量投影；event_families.py：等级关联；event_records.py：查询及删除合同；repository.py：事务、保留及引用检查；service.py：统一读取。Web 的 event_api.py、app.py 和 static/ 下对应模块承载门禁与显示。

离线入口见 [生命周期文档](EVENT_LIFECYCLE.md#离线验证)。专项包含 test_event_lifecycle、test_event_management、test_event_wording、monitoring-ui.test.mjs 和 view-model.test.mjs；预览助手 apps/management_web/tests/event_preview.py 仅创建临时数据库，不装配 AI、凭据或上报写入口。

2026-10-23 同步验收：事件 Targeted Python 32 项、Node 30 项通过；Management 独立完整入口 524 项 Python、106 项 Node 通过，阻断旧 fishery_ai 导入。虚构预览在 1440/1024/900/390px 无页面横向溢出；桌面核对升级详情、保留原等级及批次证据，390px 首页异常概况纵向排列、事件表内部滚动。没有读取或迁移正式业务数据，没有真实 Provider/NPU 请求。启动器、品牌、实例路径及 AI 权限未改动；同步结果等待最终人工验收，尚未提交。
