# QQ无回复排查与2048输出预算

2026-11-03，Management。用户批准最小修复及QQ输出上限四倍调整。本轮仅离线／Mock验证，没有调用QQ或Qwen，没有读取密钥或业务数据库，没有改Prototype。

## 实际原因

既有 `outputs/management-stack/stack-ee2c4fae673041319c134e398eb31b4a/bot-run` 的两轮非敏感结果：

| 轮次 | 原始证据 | 结果 |
|---|---|---|
| 1 | `INVALID_TOOL_ARGUMENTS`；`UNEXPECTED_ARGUMENTS`，35字节、1字段；Handler未启动；1次模型请求 | 工具仅允许空对象，模型多传参数；未知字段名和值未保存，不能推测具体内容 |
| 2 | Tool Handler成功；2次模型请求；第二次 `finish_reason=length`、输出512 Token；`ASSISTANT_RESPONSE_TRUNCATED` | 回答不完整，被成功答复门禁拒绝 |

两轮均 `SDK=CLOSED`、本地I/O关闭、请求线程退出；均无成功QQ回复及成功历史。程序执行耗时分别约2.578秒和14.937秒，不是无限等待。主动私聊事件通知走独立的零模型链路，正常发送不证明AI回答成功；`AI_ADMITTED`只代表已准入。

## 本轮修改

### 独立Management QQ预算

- 新 `ai_service/management_channel_budget.py` 统一2048 Token／请求和费用计算；Web Normal／Streaming与旧Fake／单轮合同默认值不变。
- 当前Management QQ授权、每轮Decision、实际SDK `max_tokens`、Usage上限校验、Run账本、Scope、审批摘要全部一致为2048。原有5 Turn、2请求／Turn、90秒、零重试、单worker／2等待位不变。
- 原通用Backend不变。Service只对确切的 `ManagementLiveTurn` 且有效许可设置2048传输上限；Web原预算与其他类型没有此路径。
- ChannelBudget允许表达2048，不代表自动授权；旧入口仍使用旧预算并受其固定合同检查。RunLedger支持子类固定预留，旧默认仍为512和1.602765元。

沿用原静态价格假设与100万输入Token／请求的保守算法：

`ceil_6(((1,000,000 × 0.8 + 2048 × 2.7) × 2) / 1,000,000) = 1.611060 元／Turn`

五轮最低 **8.055300元**，当前默认批准总预算 **8.06元**。不足时拒绝计划，不减少轮数、不借用旧许可、不退款。该数字不是实际费用预测、最新云价格核验或云账单硬上限，最终账单未知。

### 参数与输出提示

Management专属 Prompt `QQ_MANAGEMENT_HYBRID_DIALOGUE@4`，继承原Hybrid能力并明确 Tool arguments 严格为字符串 `{}`，不得增加设备／问题／指标字段，设备由服务器固定；Tool之后只输出既有Water计划JSON，不复述整份报文。Tool Schema、参数校验和领域规则不变，不自动删掉错误参数后继续执行。

扩大模型生成预算不扩大QQ消息长度、General文本上限或事实发布范围。General／Water仍按原结构、来源、Source与Commit条件处理；非法／截断文本不放行。提示词不能保证真实模型永远遵循，真实稳定性仍需用户复测。

### 失败不再静默

Management装配显式启用失败反馈；旧Scheduler调用默认不改变。只有本次两种已确认错误允许发送程序固定短句：

- 参数错误：“本次查询未完成：AI生成的工具参数不符合要求，未取得有效结果。没有自动重试。”
- 回答截断：“本次查询未完成：AI回答达到输出上限而被截断，未发送不完整的水质结论。没有自动重试。”

错误提示不携带模型正文、现场数值或新事实，不作为成功答复，不提交历史。发送前仍复核任务归属、对应失败原因、群／成员／设备、Scope／权限、截止时间、连接状态及SDK资源安全关闭；复用同一PassiveReplyOwner，一条原消息最多提交一次。撤权、取消、过期、SDK清理失败时不会为提示而绕过门禁。

未知送达／HTTP错误不重发，不重新推理；费用仍保守消耗。错误提示单独存 `turn-N.failure-notice.json`，其中 `successful_ai_reply=false`、`history_committed=false`。原Turn仍 `FAILED`、顶层 `api_accepted=false`；仅 `failure_notice.api_accepted=true` 表示QQ接受了错误提示，不能当作AI成功或客户端显示证据。必要检查点失败后Run停止新AI。

终端新增脱敏 `AI_TASK_FINISHED`，含随机任务摘要、state、reason、AI成功回复／错误提示的API接受状态。使用有界队列由原控制器输出，无新增线程，无聊天正文或完整平台身份。Trace仅给当前水质Tool加入已知名称白名单，参数诊断仍只含固定类别和数量。

## 配置、Scope与备份

两份QQ候选准备资源按实际源码重算，仍为candidate，`qualification_id=null`。真实运行必须重新建立当前进程RunConsent，不能复用旧单轮／双轮批准、used或历史回执。

本机既有配置只调整：

1. `ai.json` 的 `budget.max_output_tokens`：512 → 2048。
2. `request.json` 的 `limits.total_budget_cny`：8.02 → 8.06。
3. `request.json` 的 `scope_sha256`。

群、成员、实例、设备、模型、期限、轮数、权限和私聊接收人逐项验证不变。未创建最终批准、未读取或迁移凭据。配置防覆盖私有备份为 `outputs/qq-bot/sync-maintenance/reply-fix-2b6dfaeded5a/`；其中含身份配置，不应交给组员。源码与原工作树补丁备份在 `outputs/qq-reply-fix-b0cd9fbe1b6e/`。用户原有技术路线文档移动未改动。

本机Check通过：2048 Token、5 Turn、8.06元，`credential_checked=false`、`database_opened=false`、`network_requests=0`；`outputs/qq-reply-fix-actual-check.log`。

## 离线验证与人工复测

新增9项测试覆盖：实际SDK2048请求、超过512的有效Usage、2048以上Usage拒绝、预算不足、五轮预留、错误参数零Tool读取、回答截断、重复消息、一次错误提示、未知送达、撤权、历史不提交及检查点失败。`outputs/qq-reply-fix-new-tests.log` 全部通过。首次专项中的重复消息夹具重新生成了时间戳，触发了正确的 `MESSAGE_ID_CONFLICT`；改为重放同一原始事件，未放宽去重检查。

完整Management回归：**Python 783／783、Node 128／128**，`outputs/qq-reply-fix-full-regression-final.log`，Python约494.377秒。旧Web、评分、SDK、事件、Monitoring、Simulator、QQ及Windows启停／打包均使用离线合成夹具。

首轮完整回归的8项启动失败定位到 `scripts/dev/management_stack.py` 仍从旧512合同模块导入配置复核；仅将导入改为Management专属复核，保留同一身份／锁检查。修复后三终端专项 **10／10**（`outputs/qq-reply-fix-stack.log`），再完整重跑783项与128项全部通过。首轮日志保留，未删除测试、弱化断言或扩大超时。

修改范围：`channel.py`仅扩展可表达预算上限，默认不变；`channel_trial.py`、`channel_session_run.py`支持由可信类型提供限额，旧默认不变；`channel_management_live.py`、新预算模块及Service的确切类型分支装配2048。QQ的配置／Run／账本／Coordinator／Scheduler／Delivery负责新预算与固定失败提示，两个示例同步新值，编排器仅改一处复核导入。原通用Backend、Monitoring、Web页面与启动参数没有修改。新旧候选资源、必要文档和测试已更新，未commit／push。`git diff --check`与本次文档链接检查通过。

人工下一步（不要重新初始化实例或迁移密钥）：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_Management'
# 正常停止旧Bot后，先检查
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check
# 沿用带视频三终端入口，人工批准本次新摘要
.\scripts\dev\启动QQ视频演示系统.cmd
```

在原授权群真正@机器人发送一条“现在水质怎么样？”。核对终端终态、QQ回复与History；用户自行确认客户端显示。若失败，应见明确原因或安全错误提示；不要连续重发试图自动重试。QQ提示路径与新Prompt仅经过Mock验证，本轮没有新的真实Provider／QQ验收证据。
