# 事件私聊提醒：交付与验收

2026-11-03。本次选择性合入 Prototype 已验证的通知机制和“鳗鲡养殖智能体”身份说明。没有整体覆盖 apps、Backend、Web 或启动器。

## 操作者只需这样做

在 Management 根目录正常运行：

```powershell
.\scripts\dev\启动QQ演示系统.cmd
```

1. Simulator 窗口选择低溶解氧、疑似疾病或“溶解氧快速下降后逐步回升”。
2. Bot 窗口核对本次模型、SIMULATOR 实例、设备、群成员、预算，以及新增的“已验证好友”摘要。按窗口要求输入新的 `APPROVE MANAGEMENT ...`。
3. 新异常、等级升级和可靠消退会尝试发到已验证的私聊对象，不再尝试群主动发送。连续同级命中和 ACK 不重复刷屏。
4. 在 QQ 私聊人工确认消息；API 接受和客户端显示是两份不同证据。不要把“规则条件消退”理解为治愈。

私聊只收通知；AI 问答仍在原授权群中 @机器人。可以在群里问“你是谁？”核对新的产品身份，程序模板不会调用模型。

停止方法不变：正常 Ctrl+C 停止本次 Bot/整组服务。单独停止 Bot 不终止 Web 或 Simulator。本轮没有改动 Management 原有 Run 最长30分钟、5个付费 Turn 的运行合同；Prototype 的无限在线传输扩展没有在本轮直接套入 Management。

**只检查，不联网：**

```powershell
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check
```

应看到 `STACK_PREFLIGHT_OK`，通知目标 `VERIFIED_PRIVATE_RECIPIENT_ONLY`，以及 `credential_checked=false`、`database_opened=false`、`network_requests=0`。这不是已经批准联网。

## 配置与数据保护

- 当前专用请求仍为 `outputs/qq-m3-real-config/request.json`。仅更新当前代码 Scope，并新增显式 `event_recipient_file` 字段；模型、额度、群成员、实例及设备不变。
- 接收人独立绑定位于 `outputs/qq-bot/event-recipient.json`，来源于同 App 成功的主动私聊验证。只保存必要的接收人平台标识与证据摘要，不含密钥，也不依赖 Prototype 的运行路径。
- 原请求配置先在 `outputs/qq-bot/sync-maintenance/` 唯一目录中保存受保护副本；具体路径见同目录维护记录。没有修改旧审批、used 标记、历史回执或数据库。
- 新接收人文件不是发送许可。每个新 Bot 进程仍须人工审批通知披露。普通请求没有 `event_recipient_file` 时不启用通知，不会继承其他实例的接收人。
- 配置含个人平台标识，不要把 outputs、私有凭据或维护备份打包给组员。组员需自己的配置和批准。
- 不自动创建或升级业务数据库，不开放 ACK、删除、设备控制或新的 AI Tool。

## 安全与实际限制

通知是独立规则读取与发送，不调用 Qwen，不消耗 AI Turn，不更改 Monitoring 事件。每5秒轮询；10秒最多一次、每日最多100次尝试。提醒文案保留 SIMULATOR、设备、观测时间和疑似非确诊边界。

发送前检查：当前进程批准、接收人文件摘要、App、绑定实例/设备、Scope、权限、Gateway READY 及运行状态。接收人或授权改变时停止，不回退到群或另一个好友。只读事件快照按设备查询，有256条、单条64KiB及总2MiB预算，超限拒绝整个查询，不截断风险周期。

写前日志先保存并 fsync `CLAIMED`，再提交无 `msg_id/event_id` 的主动私聊消息。失败、未知送达和重启均不自动重发同一通知；日志异常或达到容量时停止提醒并报告。SDK资源门禁仍按 Management 原合同检查，没有修改 M1 的线程启动前租约保护。

本次实际连续事件提醒尚需人工联网验收；Codex 只运行 Fake Gateway/MockTransport。此前客户端主动私聊成功并不保证永远有发送权限。快照轮询可能漏掉两次轮询间发生又结束的短周期，不宣称恰好一次送达。

最终 `bot-run/result.json` 中 `event_notifications.accepted` 是平台接受次数；`delivery_unknown` 是未知次数，`client_display_confirmed` 不由程序自动改真。客户端显示请由操作者另行记录。

## 交付和回退

保留本仓库独有启动器、私有凭据位置、原 Web/知识库/Simulator 和事件写入逻辑。只同步通知、身份、受限只读事件快照及必要的候选 Scope、测试和说明；没有同步评分 Tool、视频页面或设备报告适配等其他 Prototype 差异。

如需停用提醒，在停机后创建一份不含 `event_recipient_file` 的新请求，继续使用当前 Scope 和原预算，显式选择它启动；不要删除通知去重日志。若要回退源码，应连同对应 Scope 与请求备份一起恢复，在停写并保留所有新运行报告后操作。本轮不自动回滚、不 commit/push。
