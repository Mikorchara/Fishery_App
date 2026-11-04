# QQ Hybrid Bot：当前合同与排错

首次部署看 [部署与配置](../guides/DEPLOYMENT.md)，日常只看 [启动指南](../BUILD_RUN.md)。本页合并原 M1/M2/M3、事件私聊和无回复修复中的当前有效约束，不保留阶段性重复命令。

## 架构与权限

QQ Bot 独立进程 → Gateway / 固定指令 Router → Coordinator / 有界 Scheduler → ManagementAssistantService → 原 AssistantService / ToolCallingService → SDK Adapter 或当前水质 Tool。工具通过 MonitoringService 与只读 Repository 读取明确绑定的实例。

- Web 和 Simulator 不导入或依赖 Bot 启动；Bot 的 SDK 隔离状态不跨进程传给 Web。
- 只处理平台认证的群 @ 事件，固定指令优先。伪造 @ 文本、昵称或聊天内容不能取得权限。
- 只开放当前水质；无 Knowledge、历史/事件 AI Tool、评分、ACK、删除、配置写入或设备控制。
- 实例和设备由可信本机配置冻结。缺库、旧 Schema、损坏和查询超预算拒绝，不建库、不迁移、不回退到 Demo。
- Repository 使用 SQLite mode=ro、query_only、写操作禁止、设备范围与查询预算；模型不直接接触 SQL。

## General / Water 与记忆

General 通常1次请求、0 Tool，属于实验性普通聊天/概念解释，不是现场核验、项目知识库证据或专业保证。有限文本防护存在漏检和误拦风险。

Water 最多2次请求、1 Tool；本轮当前事实必须来自实际 Tool Steps / Receipt / SourceSummary。继续使用封闭水质解释合同，保留 SIMULATOR、观测/评估时间、质量、新鲜度和连接状态。旧低氧读数不能据此生成当前 HIT；无 HIT 也不等于能排除风险。General 声明不能掩盖实际发生的 Tool 步骤。

Chat 展示是同轮可信事实与经校验解释的投影，不重新查询/调用模型。普通 QQ CLI 默认禁用，真实入口只能经 Management 本进程批准。

内存 ConversationStore 按 App、群、成员、实例、设备、授权代次和 Scope 隔离，6个成功 Turn、15分钟空闲过期、64会话、每会话24KiB、全局1MiB、Agent 历史投影约4KiB。只在 Backend/Source/Commit、SDK关闭、QQ API明确接受且文本哈希与会话CAS均通过后提交实际发送的安全文本。未知交付、失败和撤权不写成功记忆；`/清空会话` 不恢复额度；退出清空 RAM。

## RunConsent、预算与生命周期

合同为 `management-qq-hybrid-process-run@1`，准备资源仍为 candidate、qualification_id=null。不是 released，也不继承 Prototype 或旧实验批准。人工本次审批派生不可反序列化的内部许可与 TurnLease。

当前固定 `dashscope-qwen38-flash-r1` / `qwen3.8-flash`；最长1800秒、5 Turn、最多10请求、2048输出Token/请求、90秒/Turn、零重试，1 worker、2等待位置。每轮保守预留1.611060元，默认总预算8.06元。准入成功后失败、取消、拒绝或未知送达不退款；BUSY与未授权不扣费。额度不是云端最终账单硬上限。

批准绑定当前进程、源码 Scope、Prompt、Tool、预算、成员、实例和设备。独占锁与写前 fsync 账本防止批准被多个进程消费；复制文件或重启不能恢复旧额度。权限、Scope、绑定或所有权变化失效，严重 SDK/账本故障停止 AI。

**当前 Management 整个 Bot 仍按本次运行期限退出。** 不将 Prototype 的“QQ长期在线、AI许可单独到期”行为写成已在 Management 实现。Bot 到期不会自动终止 Web/Simulator；关闭整组由编排器处理。

## SDK 与单次交付

沿用 RequestHandle、SDK资源租约、取消、Client/Stream关闭和线程退出确认；不使用已清理的子进程草稿。取消请求、本地 I/O 中断、线程退出和远端停止计费是不同状态。

清理无法确认时隔离该 Bot 进程，不成功 Commit、不继续交付、不清零门禁重试。不合作线程仍可能无法强制终止；进程边界限制对 Web 的影响，但不保证远端计算或计费停止。

每个 QQ 原消息只有一个被动回复 Owner，发送前重查权限、Scope、期限和SDK状态。API超时或结果未知不重发、不重新推理。API接受不自动等于客户端实际显示；人工验收另记。没有额外“正在查询”消息抢占回复权。

## 事件私聊通知

默认关闭（新 request 不含 `event_recipient_file`）。启用时须绑定同 App 的受控好友接收人，并在本进程人工摘要中单独批准。只发指定设备 SIMULATOR 的新异常、等级升级、可靠消退，各一次；不重放启动前历史，连续同级HIT和ACK不刷屏。

每5秒轮询，10秒最多1次、每日最多100次尝试，不调用Qwen、不扣AI Turn。写前记录 CLAIMED 并 fsync，再主动发送；失败、未知、重启不自动重发。通知日志不能删除来重置去重。

`event_recipients` 只会从已有、成功的受控主动私聊探测报告生成接收人：

```powershell
# 仅维护者使用；输入必须是已授权的成功报告，不是随意填写的QQ号码。
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.event_recipients --probe-directory '<成功报告的本机绝对目录>' --output '<全新接收人JSON绝对路径>'
```

该命令不联网、不批准发送；还需受控绑定 request 并重新 Check/审批。**Management 尚未提供独立的私聊探测入口与新接收人绑定向导**，新电脑应默认不启用通知，由维护者另行处理，不把 Prototype 作为运行依赖。群主动发送曾被平台拒绝；不能用好友通知成功推定群权限可用。

轮询可能遗漏两次快照之间已经结束的短周期，不宣称恰好一次送达。`QQ_EVENT_NOTICE_API_ACCEPTED` 只说明平台接受；“规则条件消退”不表示治愈或人工处理完成。

## 安全状态与排错

| 状态 | 含义与操作 |
|---|---|
| AI_ADMITTED | 仅准入，不是执行/回复成功 |
| AI_TASK_FINISHED | 查看 backend、交付与错误码；不自动再发相同问题补偿 |
| INVALID_TOOL_ARGUMENTS | 参数不符合当前工具（仅{}），不绕过参数验证 |
| ASSISTANT_RESPONSE_TRUNCATED | 输出截断；最多一次固定失败提示，不发布残缺正文、不成功提交历史 |
| QQ_REPLY_API_ACCEPTED | QQ接受被动回复；客户端是否显示需人工确认 |
| DELIVERY_UNKNOWN | 不重发、不追加成功历史；保守消耗本轮额度 |
| SDK资源隔离/清理失败 | 停止新AI，保留报告，正常停Bot；不重置门禁 |
| MANAGEMENT_SCOPE_REVIEW_REQUIRED | 源码与准备/本机配置不一致；维护者审查后更新准备与新配置，不改旧批准 |
| MANAGEMENT_BOT_REPORT_SAVED | 报告落盘；还须核对结果中的backend、SDK、交付、历史和额度 |

原无回复问题曾由多余Tool参数与512输出Token截断引起；Management独立升至2048并有终态状态和一次性安全失败提示。Web输出预算没有因此改变。错误提示只在可安全发送时提交一次，不保证所有故障都能回群通知。

停止与报告路径见 [维护与回滚](OPERATIONS.md)。官方平台权限、可达性和密钥是否有效不能由离线 Check 证明；实际联网只能由操作者另行批准。
