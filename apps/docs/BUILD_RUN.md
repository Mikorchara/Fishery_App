# 日常启动

在 **Fishery_Management 根目录**打开PowerShell。新电脑先完成根目录的 [开始使用](../../开始使用.md)，已有配置的机器直接选一个入口。启动前正常停止上一次演示。

## 四个入口

```powershell
# 两终端：Simulator + Web
.\scripts\dev\启动演示系统.cmd

# 三终端：Simulator + Web + QQ Hybrid Bot
.\scripts\dev\启动QQ演示系统.cmd

# 两终端，播放项目根目录 sample.mp4
.\scripts\dev\启动视频演示系统.cmd

# 三终端，播放 sample.mp4
.\scripts\dev\启动QQ视频演示系统.cmd
```

1. 先选运行模式：`1`完整模拟（默认）；`2`设备联调（仅模拟水质）；`0`退出。再在 **Simulator窗口**选场景，Enter默认正常，0退出；选择前不发送新数据，首个完整窗口约10秒。
2. 打开 http://127.0.0.1:8766 。视频在“视频监控”，两侧数据可收起。右上角切换浅色/深蓝主题。
3. 三终端需在 **Bot窗口**核对本次模型、群/成员摘要、实例、设备、时间和费用，输入本次 `APPROVE MANAGEMENT <摘要>`。未批准不联网。

| 输入 | 场景 | 直接指定时的参数 |
|---|---|---|
| 1 | 正常水质 | normal |
| 2 | 低溶解氧 | low_oxygen |
| 3 | 疑似疾病信号 | suspected_disease |
| 4 | 摄食减少 | reduced_feeding |
| 5 | 复合异常 | combined_anomaly |
| 6 | 设备离线 | device_offline |
| 7 | 溶解氧快速下降后逐步回升 | oxygen_drop_recovery |

设备联调模式停发模拟视觉；疑似疾病/摄食等视觉参数不生效，水质场景仍生效。四个cmd不会自动开启局域网接收器或猜测设备绑定；选择2但未绑定报告目录时，页面明确显示未接入。真正接设备请按 [设备连接步骤](DEVICE_INTERFACE_QUICK.md) 显式指定目录、设备ID并单独启动接收器。

## 数据和AI要点

- **四个日常cmd统一使用 `outputs/qq-m3-real-test`**，以当前QQ三终端的数据为主。两终端显式指定此目录；三终端沿用 `outputs/qq-m3-real-config/request.json` 中同一绑定。水质、事件、知识库、设置和Web工具授权共用一份实例；QQ独立权限和凭据规则不变。目录缺失时拒绝启动，不自动初始化另一份数据。
- `outputs/demo-instance`、旧 `%LOCALAPPDATA%\FisheryManagement` 和其他测试实例原样保留；四个日常入口不再选择它们，不混合或覆盖旧历史。`run_local.ps1 -Demo`、`--user-data` 和手动 `--data-root` 仍是显式选择其他实例的维护入口，不用于本机日常运行。运行日志、备份、测试夹具和私有密钥不属于第二份日常业务库。
- 本地录像标为LOCAL VIDEO，与SIMULATOR水质/视觉、事件和时间独立；不做实时检测或NPU推理。
- 两个视频入口显式启用Web实验评分。还须在设置勾选“水质实验评分”并确认本次模型发送。原无视频三终端关闭Web AI；QQ始终只有当前水质只读Tool。
- QQ群中真正@机器人，可问“什么是溶解氧？”、“现在水质怎么样？”、“那溶解氧呢？”。`/清空会话`只清自己的记忆。普通自然语言可能收费。
- 展示时直接发送 `@机器人 /当前水质`、`@机器人 查询水质` 或 `@机器人 查询当前水质`，由系统直接查数据，不调用模型、不扣AI轮数。只有这几个明确指令走直接查询；`/问AI 查询水质`仍调用模型。
- 新配置仍默认30分钟、5轮、预算8.06元。Management现支持预算模式：request的`limits.max_turns`设为`null`，以明确批准的总预算决定可用轮数。例如`seconds: 7200`、`total_budget_cny: "100.00"`可预留62轮，运行2小时；不是预估会花100元。每轮最多2请求、2048输出Token/请求、90秒、零重试，失败仍消耗许可。**运行到期Bot会退出**，不自动续批；Web/Simulator可继续运行。预算不是云账单硬上限。
- 新配置默认无事件通知。已受控绑定接收人并另行批准时，只向已验证好友发指定设备的SIMULATOR新异常、升级和可靠消退；私聊通知不是私聊AI问答。详见 [QQ合同](deep-dive/QQ_BOT.md)。

## 检查、指定场景和停止

```powershell
# 只检查，不联网、不读取密钥、不打开数据库
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check

# 三终端，跳过菜单直接选低氧；Bot仍需人工审批
.\scripts\dev\Start-ManagementStack.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -WithBot -NoAssistant -Scenario low_oxygen -OpenBrowser
```

需要运行模式菜单时加 `-InteractiveMode`；直接指定模式用 `-SimulationMode water-only`（默认full）。需要场景菜单时加 `-InteractiveScenario`；需要视频时加 `-DemoVideo "$PWD\sample.mp4"`；Web评分加 `-ScoreTrial` 并去掉 `-NoAssistant`。`-Port 8767`可改端口，不结束未知Python进程。PowerShell接受相对Request路径，JSON内部仍必须是本机正确的绝对路径。

**停止：**三终端在最初编排终端Ctrl+C；两终端可在Web或Simulator窗口Ctrl+C。单独关闭Bot不停止其他两项。优先正常停止以保存结果。独立停止、日志与备份见 [维护说明](deep-dive/OPERATIONS.md)。

**事件清理：**已恢复历史可普通删除；任何活动、未知或人工留痕记录也可在列表/详情选择“删除此轮事件”彻底删除。事件页“清空全部事件记录”删除当前实例的全部事件及ACK/人工结束历史，不受筛选和分页影响，确认一次提交。水质数据和原始设备报告保留；异常持续时，下一份新上报仍可能产生新事件。代码更新后重启Web并按Ctrl+F5。完整规则见[事件管理](deep-dive/EVENT_MANAGEMENT.md)。

**Ctrl+F5仅强制重新加载网页资源，不清数据库、事件、水质历史、设置或密钥。** 删除数据必须使用明确的删除/清空入口并确认。

## 已配置QQ的设备联调

先按 [连接步骤](DEVICE_INTERFACE_QUICK.md) 初始化并启动独立接收器；再使用原QQ实例启动三终端：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -WithBot -NoAssistant -SimulationMode water-only -DeviceReportDirectory "$PWD\outputs\device-reports" -DeviceReportDeviceId fish-monitor-orin-01 -InteractiveScenario -OpenBrowser
```

需要录像再加 `-DemoVideo "$PWD\sample.mp4"`。绑定后Web会把新鲜设备异常同步到事件列表；Bot原审批会一并显示该设备的视觉异常通知范围，使用已有已验证私聊接收人。AI仍只查询原授权模拟水质，设备提醒不调用模型。同类报告合并提醒，过期只显示状态待核实，不自动判定恢复。独立接收器是额外的第四个终端，需单独Ctrl+C关闭。详见[设备连接步骤](DEVICE_INTERFACE_QUICK.md)。

本次设备接入改变了 Web 启动文件，QQ代码指纹随之更新。已有本机request若提示 `MANAGEMENT_SCOPE_REVIEW_REQUIRED`，应由维护者审查后生成匹配当前准备记录的新request，再Check并重新人工审批；不要复用旧批准或手工关闭指纹检查。本次同步未修改任何已有request或批准。

## 本机模型排查（可选）

以下入口只使用新建模拟实例，不连接QQ、不发送群消息。默认离线检查；加`--run`须在终端另行批准，才从Management私有凭据存储请求Qwen。每批1～20题，默认6题、最多12次HTTP，失败停批、不自动重试。结果在`outputs/provider-checks/`；没有QQ客户端验收含义。

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/check_qq_provider.py
.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/check_qq_provider.py --run --cases 6
```

若报`PROVIDER_CREDENTIAL_UNAVAILABLE_NO_REQUESTS`，在此前能正常调用Web/Bot的Windows账号终端运行；不要复制密钥到命令行，也不要放宽凭据目录权限。
