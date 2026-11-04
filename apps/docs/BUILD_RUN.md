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

1. 在 **Simulator窗口**选场景，Enter默认正常，0退出；选择前不发送新数据，首个完整窗口约10秒。
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

Management当前入口只有上述场景菜单；Prototype独有的“完整模拟/设备联调”模式尚未同步，不要按另一项目的菜单操作。

## 数据和AI要点

- 两终端cmd使用 `outputs/demo-instance`，首次需要可复制的正式知识库；三终端使用 `outputs/qq-m3-real-config/request.json` 指定的 `outputs/qq-m3-real-test`。**两份数据不自动同步。** 新电脑没有正式知识库时，使用部署指南的独立初始化路径。
- 本地录像标为LOCAL VIDEO，与SIMULATOR水质/视觉、事件和时间独立；不做实时检测或NPU推理。
- 两个视频入口显式启用Web实验评分。还须在设置勾选“水质实验评分”并确认本次模型发送。原无视频三终端关闭Web AI；QQ始终只有当前水质只读Tool。
- QQ群中真正@机器人，可问“什么是溶解氧？”、“现在水质怎么样？”、“那溶解氧呢？”。`/清空会话`只清自己的记忆。普通自然语言可能收费。
- 当前QQ批准最长30分钟、5 Turn、每请求2048输出Token、最多2请求/Turn、90秒、零重试；总预算8.06元，不是云账单硬上限。**本次运行到期Bot会退出**，不会自动续批；Web/Simulator可继续运行。
- 新配置默认无事件通知。已受控绑定接收人并另行批准时，只向已验证好友发指定设备的SIMULATOR新异常、升级和可靠消退；私聊通知不是私聊AI问答。详见 [QQ合同](deep-dive/QQ_BOT.md)。

## 检查、指定场景和停止

```powershell
# 只检查，不联网、不读取密钥、不打开数据库
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check

# 三终端，跳过菜单直接选低氧；Bot仍需人工审批
.\scripts\dev\Start-ManagementStack.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -WithBot -NoAssistant -Scenario low_oxygen -OpenBrowser
```

需要场景菜单时加 `-InteractiveScenario`；需要视频时加 `-DemoVideo "$PWD\sample.mp4"`；Web评分加 `-ScoreTrial` 并去掉 `-NoAssistant`。`-Port 8767`可改端口，不结束未知Python进程。PowerShell接受相对Request路径，JSON内部仍必须是本机正确的绝对路径。

**停止：**三终端在最初编排终端Ctrl+C；两终端可在Web或Simulator窗口Ctrl+C。单独关闭Bot不停止其他两项。优先正常停止以保存结果。独立停止、日志与备份见 [维护说明](deep-dive/OPERATIONS.md)。

**事件删除：**列表或详情选择“删除已结束周期”，核对原始记录和ACK历史数量，确认一次即可。活动、恢复观察、状态待核实及人工结束留痕仍受保护。代码更新后重启Web并按Ctrl+F5。
