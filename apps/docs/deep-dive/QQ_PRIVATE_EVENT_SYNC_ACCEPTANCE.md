# QQ 私聊事件提醒：选择性同步验收记录

日期：2026-11-03。范围为事件私聊提醒与产品身份文案，先 Prototype 后 Management；不含其他尚未同步的评分、视频和设备适配功能。无 commit/push。

## 源码基线与实际合入

Prototype：`main / 640f17f`，开始时已有前一阶段通知、身份和私聊探针等未提交改动，全部保留。

Management：`codex/mig3-baseline / e2ab3c4`，开始时工作树干净；本轮选择性合入后保持未提交。两仓库 HEAD 和分支未改变。

| 范围 | 文件/行为 |
|---|---|
| 通知及接收人 | 新增 `apps/qq_bot/event_notifications.py`、`event_recipients.py`；Management 严格校验本项目 `ManagementRun`/当前进程许可，不导入 Prototype |
| Management 装配 | 修改 `management_cli.py`、`management_config.py`、`management_run.py`；可选显式接收人字段、启动审批、通知工作线程及最终报告 |
| QQ 边界 | `transport.py` 新增类型化通知发送和有界数字错误码解析；保留 Management 默认无网络构造限制。`gateway.py` 仅增加 READY/断线状态供通知使用，不覆盖其独有许可校验 |
| 只读事件 | Repository 新增按设备的有界 `capture_events`；Service 增加可选设备参数，旧无参数路径不变；`monitoring_source.py` 只读调用。没有 Schema、阈值、恢复、ACK 或删除逻辑变更 |
| 身份 | `channel_identity.py`、`intent.py`、`hybrid_intent.py`、`channel_hybrid.py`；自称鳗鲡养殖智能体，身份不授予新能力 |
| 候选 Scope | 更新 Management 自身两份候选准备资源；实际源码和 Prompt 摘要变化后必须重新人工审批，没有提升 released 资格 |
| 验证 | 新增通知专项，补充两个只读预算/设备隔离测试；现有 Web、Backend、AI工具循环、启动器和页面均未整体覆盖 |

未复制 Prototype 的私聊探针、研究脚本、批准、used 标记、历史报告、数据库或凭据；Management 运行时不需要 Prototype 目录。接收人绑定是从同 App 已成功的探针显式准备出的最小非密钥配置，发送许可仍由 Management 新进程审批。

## 自动化结果

Management 修改前完整基线：Python **739/739**、Node **121/121**。首次未启用 UTF-8 的运行有3个读取中文日志的 GBK 解码错误；改用 `-X utf8` 后原基线通过，没有删除或弱化原测试。

Management 合入后完整回归：Python **753/753**、Node **121/121**，日志 `outputs/private-notices-full-regression.log`。新增私聊专项最终 **13/13**，包括完整 Fake Gateway 控制器到通知发送和最终报告的追加测试；该追加1项是在完整回归发现测试集后加入，单独运行验证。首次合入兼容专项36项通过，独立打包/隔离导入检查1项通过。

Prototype 通知、私聊、传输专项 **98/98**。最终完整回归 Python **1343/1343**、Node **129/129**，日志 `outputs/private-notices-full-regression-final.log`。首轮没有把 TEMP/TMP 指到仓库内，7项启动器测试按预期拒绝外部临时目录，该环境失败日志保留。复核使用仓库内 `outputs/test-tmp`，没有放宽路径检查。

重点覆盖：同级去重、升级、可靠消退、未知/失联不当 CLEAR、重启防重、发送前撤权、接收人修改、日志 fsync 和检查点失败、API 接受事实保留、平台数值错误、预算不消费、只读数据库不变、跨设备隔离、SDK/旧 AI 路径、Windows 三终端及打包。最终 `git diff --check` 和新增文档链接检查通过。

## 本机配置与操作边界

两边各自准备 `outputs/qq-bot/event-recipient.json`；只显示接收人摘要，不输出完整 OpenID。Management 专用请求只更新 `scope_sha256` 并增加 `event_recipient_file`，其余模型、群成员、数据根、设备、额度均验证不变。

Management 原请求备份位于：

`outputs/qq-bot/sync-maintenance/sync-20261103T111356Z-eb5f5cb2/request.before.json`

同目录 `maintenance.json` 记录变更前后摘要和边界。备份和新配置均受本机访问保护，不能交给组员。未改旧审批/used/Provider 回执；旧源码 Scope 的批准不能用于本轮。

实际 `Start-QQBot.ps1 -Check` 已通过，明确 `credential_checked=false`、`database_opened=false`、`network_requests=0`；本轮不调用真实 QQ/Qwen，不读取密钥，不打开正式或演示业务库。

## 尚需人工验收

1. 正常停止旧 Bot，执行原 `启动QQ演示系统.cmd`。
2. 选择异常场景，在 Bot 窗口核对已验证好友、设备、SIMULATOR及原额度，重新审批。
3. 等网页产生可靠活动异常，核对私聊收到新异常；持续同级不重复；回升场景核对升级和可靠消退。
4. 核对 `QQ_EVENT_NOTICE_API_ACCEPTED` 与最终报告，并由用户独立确认客户端显示。

此前单条主动私聊的客户端显示已经由用户确认；自动连续事件提醒还未联网验收。快照轮询不是持久事件队列，可能漏过很短周期；平台权限、好友拒收和容量限制仍可能导致停止通知。

Management 保留原30分钟运行合同，没有本轮扩展无限在线或自动续批。停用提醒可在停机后显式使用不含接收人字段的当前 Scope 请求。不要删除去重日志来重放通知，不自动重启旧批准。
