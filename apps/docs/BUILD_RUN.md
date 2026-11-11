# 日常启动

在 **Fishery_Management 根目录**打开PowerShell。新电脑先完成根目录的 [开始使用](../../开始使用.md)，已有配置的机器直接选一个入口。启动前正常停止上一次演示。

首次安装依赖后，只需执行一次 `.\scripts\dev\Initialize-Management.ps1`：自动创建 `outputs` 和唯一日常实例，带31条初始背景资料，不需要QQ或模型密钥。已有数据拒绝覆盖；之后需要QQ时在网页“系统设置 → QQ机器人”添加配置，步骤见根目录指南。不删除 `outputs` 来“重置配置”。

**尚未配置QQ时，先用两终端打开网页设置QQ。** 新配置采用持续运行和自然回答，保存后重启Bot生效；不会自动连接或调用模型。步骤只在根目录[开始使用](../../开始使用.md#6-可选开启-qq-机器人)维护，机制与兼容说明只看[QQ专题](deep-dive/QQ_BOT.md)。


**需要接受设备发来的数据时**
首次使用先按[设备连接步骤](DEVICE_INTERFACE_QUICK.md#1-先准备电脑)初始化报告库。日常在项目根目录另开一个 PowerShell 窗口，用 `ipconfig` 查看电脑当前的局域网 IPv4，替换下面的占位符后启动接收器。

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Serve -Bind '<电脑局域网IPv4>' -DeviceId fish-monitor-orin-01
```

看到 `DEVICE_REPORT_LISTENING` 后保留这个窗口。接收器使用 `8780` 端口，已运行时可直接进入下一步。需要停止接收时，在接收器窗口按 Ctrl+C。


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
3. 三终端需在 **Bot窗口**核对本次模型、群/成员摘要、实例、设备、Token和持续调用费用，输入本次 `APPROVE MANAGEMENT <摘要>`。未批准不联网。

| 输入 | 场景 | 直接指定时的参数 |
|---|---|---|
| 1 | 正常水质 | normal |
| 2 | 低溶解氧 | low_oxygen |
| 3 | 疑似疾病信号 | suspected_disease |
| 4 | 摄食减少 | reduced_feeding |
| 5 | 复合异常 | combined_anomaly |
| 6 | 设备离线 | device_offline |
| 7 | 溶解氧快速下降后逐步回升 | oxygen_drop_recovery |
| 9 | 模拟开发板视觉信号（异常后消退，仅完整模拟） | device_visual_recovery |

选项`9`在完整模拟菜单中显示。水质保持正常场景。前两个10秒窗口出现疑似病灶和体表异常信号，之后连续三个完整窗口未检出，约第50秒两条事件消退。事件来源显示为`SIMULATOR`。`0`或`8`退出。

设备联调模式只模拟水质，视觉数据由开发板提供。四个入口选 `2` 后会绑定本项目 `outputs/device-reports` 和设备 `fish-monitor-orin-01`。启动前先按下方[设备联调](#设备联调)打开独立接收器。

## 数据和AI要点

- **四个日常cmd统一使用 `outputs/qq-m3-real-test`**，以当前QQ三终端的数据为主。两终端显式指定此目录；三终端沿用 `outputs/qq-m3-real-config/request.json` 中同一绑定。水质、事件、知识库、设置和Web工具授权共用一份实例；QQ独立权限和凭据规则不变。目录缺失时拒绝启动，不自动初始化另一份数据。
- `outputs/demo-instance`、旧 `%LOCALAPPDATA%\FisheryManagement` 和其他测试实例原样保留；四个日常入口不再选择它们，不混合或覆盖旧历史。`run_local.ps1 -Demo`、`--user-data` 和手动 `--data-root` 仍是显式选择其他实例的维护入口，不用于本机日常运行。运行日志、备份、测试夹具和私有密钥不属于第二份日常业务库。
- 本地录像标为LOCAL VIDEO，与SIMULATOR水质/视觉、事件和时间独立；不做实时检测或NPU推理。
- 两个视频入口启用 Web 实验评分和当前事件查询。`启动演示系统.cmd` 也启用当前事件查询。在设置里勾选相应工具并保存，发送时确认本次模型请求。无视频的三终端入口关闭 Web AI。QQ 网页保存的 Agent 配置包含当前水质、历史水质、项目知识、实验评分和当前事件五个只读工具，沿用原启动审批。已有 QQ 配置升级后在网页重新保存一次，无需填写新字段。
- QQ群中真正@机器人，可问“什么是溶解氧？”、“现在水质怎么样？”、“那溶解氧呢？”。`/清空会话`只清自己的记忆。普通自然语言可能收费。
- 展示时直接发送 `@机器人 /当前水质`、`@机器人 查询水质` 或 `@机器人 查询当前水质`，由系统直接查数据，不调用模型。只有这几个明确指令走直接查询；`/问AI 查询水质`仍调用模型。
- 网页新配置使用持续模式，不设累计时长、轮数和费用停止；普通自然语言可能持续计费，需人工停止。旧有限配置不自动升级；在网页确认保存后重启。机制和错误码统一见[QQ专题](deep-dive/QQ_BOT.md)。
- 新配置默认关闭事件通知。在网页完成接收人配对、启用通知并批准本次运行后，QQ 向已验证好友发送授权设备的 SIMULATOR 新异常、升级和可靠消退。设备联调可同时批准接收 E1 外观异常提醒。详见[QQ 说明](deep-dive/QQ_BOT.md#事件通知与设备报告)。

## 检查、指定场景和停止

```powershell
# 只检查，不联网、不读取密钥、不打开数据库
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check

# 三终端，跳过菜单直接选低氧；Bot仍需人工审批
.\scripts\dev\Start-ManagementStack.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -WithBot -NoAssistant -Scenario low_oxygen -OpenBrowser
```

需要运行模式菜单时加 `-InteractiveMode`；直接指定模式用 `-SimulationMode water-only`（默认full）。四个cmd已带`-AutoDeviceReports`，仅在water-only且未提供绑定时使用上述固定目录/ID；手动启动不加此开关时保持原行为。需要场景菜单时加 `-InteractiveScenario`；需要视频时加 `-DemoVideo "$PWD\sample.mp4"`；Web评分加 `-ScoreTrial` 并去掉 `-NoAssistant`。`-Port 8767`可改端口，不结束未知Python进程。PowerShell接受相对Request路径，JSON内部仍必须是本机正确的绝对路径。

**停止：**三终端在最初编排终端按 Ctrl+C，两终端可在 Web 或 Simulator 窗口按 Ctrl+C。单独停 Bot 时，Web 和 Simulator 继续运行。关闭浏览器标签页后，后台进程仍会运行。独立停止、日志与备份见[维护说明](deep-dive/OPERATIONS.md)。

**事件清理：**已恢复历史可普通删除；任何活动、未知或人工留痕记录也可在列表/详情选择“删除此轮事件”彻底删除。事件页“清空全部事件记录”删除当前实例的全部事件及ACK/人工结束历史，不受筛选和分页影响，确认一次提交。水质数据和原始设备报告保留；异常持续时，下一份新上报仍可能产生新事件。代码更新后重启Web并按Ctrl+F5。完整规则见[事件管理](deep-dive/EVENT_MANAGEMENT.md)。

**Ctrl+F5仅强制重新加载网页资源，不清数据库、事件、水质历史、设置或密钥。** 删除数据必须使用明确的删除/清空入口并确认。

## 设备联调

首次使用先按[设备连接步骤](DEVICE_INTERFACE_QUICK.md#1-先准备电脑)初始化报告库。日常在项目根目录另开一个 PowerShell 窗口，用 `ipconfig` 查看电脑当前的局域网 IPv4，替换下面的占位符后启动接收器。

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Serve -Bind '<电脑局域网IPv4>' -DeviceId fish-monitor-orin-01
```

看到 `DEVICE_REPORT_LISTENING` 后保留这个窗口。接收器使用 `8780` 端口，已运行时可直接进入下一步。需要停止接收时，在接收器窗口按 Ctrl+C。

在另一个窗口运行[四个入口](#四个入口)中的一个，选择 **`2`（设备联调）**。Web 会同步外观异常、行为异常和报告更新中断。若使用 QQ 入口且本次审批包含设备视觉通知，E1 会提醒已验证的私聊接收人，E2 和 E3 在网页查看。非默认设备 ID 或目录可通过 `Start-ManagementStack.ps1` 的 `-SimulationMode water-only -DeviceReportDirectory <目录> -DeviceReportDeviceId <ID>` 指定。详见[设备连接步骤](DEVICE_INTERFACE_QUICK.md)。

若提示 `MANAGEMENT_SCOPE_REVIEW_REQUIRED`，按[代码指纹与恢复启动](deep-dive/QQ_BOT.md#代码指纹与恢复启动)核对版本并重新保存现有 QQ 设置，再运行预检和批准新进程。

## Web AI 查询当前事件

用 `启动演示系统.cmd`、`启动视频演示系统.cmd` 或 `启动QQ视频演示系统.cmd` 重启后，进入「系统设置 → Assistant Tool 授权」，勾选「查询当前事件（只读）」并保存。已勾选时可直接用 Qwen 问「现在有什么异常？」。Normal 和 Streaming 都支持，发送问题并确认后才会调用模型。

日常入口的 Web AI 查询网页选定设备的事件。如需让 Web AI 同时读取已绑定开发板的事件，请按[设备联调](#设备联调)保持接收器运行，并从项目根目录手动启动。

```powershell
.\scripts\dev\run_local.ps1 -DataRoot "$PWD\outputs\qq-m3-real-test" -ShowTerminals -InteractiveScenario -OpenBrowser -ScoreTrial -EventTrial -SimulationMode water-only -AutoDeviceReports -EventBoardReports
```

需要视频可加 `-DemoVideo "$PWD\sample.mp4"`。发送前会提示事件摘要可能提交给 Qwen。

## 自动测试当前QQ Agent（可选，模型调用收费）

不必逐题在群里发送。此入口复用当前 QQ Agent，现有题库覆盖原四项工具，默认44题、重复3次，共132题；使用全新合成数据，不连接QQ、不读取日常数据库。

```powershell
# 只检查计划：不联网、不访问凭据或数据库
.\scripts\dev\Test-QQAgent.ps1 -Check

# 先跑六类冒烟样例：核对计划并批准一次，随后自动逐题执行
.\scripts\dev\Test-QQAgent.ps1 -Run -Suite smoke -Repeats 1

# 完整题库：44题 × 3次，批准一次后自动执行
.\scripts\dev\Test-QQAgent.ps1 -Run
```

只补测指定合成题时可加 `-CaseIds 'C02,C03,E01,E02,E03,E04,E05,M01,M02,M03,M04,M05'`，不能与`-Cases`同时使用。脚本会按现有QQ限流节奏等待，不会放宽机器人权限；等待单独统计。新的补测是独立计划与批准，不重放旧Run，也不修改旧报告。

Ctrl+C停止。每轮仍是最多3次模型请求、2次只读Tool、2048输出Token/请求、90秒、零重试。默认每批最多396次请求，不是预期实际调用数。普通模型或展示失败且SDK安全关闭时记录后继续下一条独立样本；权限、Scope、账本和资源故障停止。必要报告写入失败不重新推理。

结果在 `outputs/agent-research/experiment-…/result.json` 和 `cases.csv`。每题的模型正文与安全答复仅存本机私有合成实验目录，普通日志不打印；不要把运行目录上传Git。`LOCAL_REVIEW`历史不代表QQ发送或客户端显示；真实QQ群交付仍需少量人工验收。细节见[QQ说明](deep-dive/QQ_BOT.md#本机真实qwen研究入口)。

如报 `CREDENTIAL_FILE_ERROR`，说明原私有凭据存储的文件/权限检查失败，不是Qwen鉴权错误。报告会记录零请求并停止；不要把Key搬到命令行、复制密钥或关闭权限检查。正常Web/Bot可用也不保证当前测试进程的凭据环境相同，需要单独诊断。

旧 `scripts/dev/check_qq_provider.py` 保留兼容，只测旧当前水质合同，不作为多工具或多轮验收入口。
