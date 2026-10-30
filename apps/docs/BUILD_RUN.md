# 启动指南

在 **Fishery_Management 项目根目录**打开 PowerShell。下面两种方式二选一；启动前先结束上一次演示，避免端口冲突。

网页右上角可切换「浅色主题／深蓝主题」。默认浅色，本浏览器会记住选择；不切换数据实例或 AI 权限。窄屏使用同一按钮的图标。

## 1. 日常演示：只记两个入口

**两个终端：模拟器 + Web**（原入口不变）

```powershell
.\scripts\dev\启动演示系统.cmd
```

**三个终端：模拟器 + Web + QQ Bot**（需已配置 QQ/Qwen）

```powershell
.\scripts\dev\启动QQ演示系统.cmd
```

两种方式都在 **Simulator 窗口选择场景**，然后打开网页 http://127.0.0.1:8766 。Enter 默认正常水质，输入 `0` 取消并停止本次服务；选择前不发送新模拟数据，首个完整窗口约10秒。

| 输入 | 场景 | 命令参数 `-Scenario` |
|---|---|---|
| 1 | 正常水质 | `normal` |
| 2 | 低溶解氧 | `low_oxygen` |
| 3 | 疑似疾病信号 | `suspected_disease` |
| 4 | 摄食减少 | `reduced_feeding` |
| 5 | 复合异常 | `combined_anomaly` |
| 6 | 设备离线（停止上报） | `device_offline` |
| 7 | 溶解氧快速下降后逐步回升 | `oxygen_drop_recovery` |

三终端还需在 **Bot 窗口**核对配置，再输入窗口本次显示的 `APPROVE MANAGEMENT <摘要>`；未批准不联网。QQ READY 后由授权成员真正 @机器人，即可问“现在水质怎么样？”、“那溶解氧呢？”；`/清空会话` 仅清空当前成员记忆。

本机三终端入口使用 `outputs/qq-m3-real-config/request.json`，三个服务共用 `outputs/qq-m3-real-test` 隔离 SIMULATOR 实例；两终端原入口使用另一份 `outputs/demo-instance`，数据不会自动同步。QQ 初始额度为30分钟、5个付费 AI Turn，总保守预留8.02元；并非实际费用预测或云账单硬上限。普通自然语言可能收费，数据及必要上下文会发给 Qwen/QQ。

**停止：**三终端在最初的启动 PowerShell 按 Ctrl+C；两终端可在 Web 或 Simulator 窗口按 Ctrl+C。单独关闭 Bot 不影响 Web/Simulator。优先正常停止以保存报告。

## 2. 需要指定场景或检查配置时

三终端等价的完整命令（显示场景菜单）：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -WithBot -NoAssistant -InteractiveScenario -OpenBrowser
```

不显示菜单、直接使用低氧场景：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -WithBot -NoAssistant -Scenario low_oxygen -OpenBrowser
```

只检查，不联网、不读取密钥或打开数据库：

```powershell
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check
```

`-InteractiveScenario` 开启菜单，菜单选择优先于 `-Scenario`；省略该开关时不会等待输入。`-NoAssistant` 只关闭 Web AI，不关闭 QQ AI；`-Port 8767` 可换网页端口。现在 PowerShell 入口也接受相对于当前目录的 `-Request`，会在本机转为绝对路径后按原规则校验；JSON 内部仍须是本机正确的绝对路径。

## 3. 第一次交给组员运行

复制文件夹不代表配置和密钥可直接复用。新电脑或项目换路径后，请按 [组员首次配置](deep-dive/MANAGEMENT_HANDOFF.md) 重新建立环境、隔离实例及 QQ 配置；不要复制私有密钥、旧批准或 used/运行账本。已在当前路径配置好的机器不需反复初始化。

- 环境：Python 3.11+、Node；依赖含可选 QQ 组件。
- QQ：本机录入 AppSecret；DashScope Key 在 Management Web「系统设置」配置。
- 原两终端入口需要已存在的演示实例，或可供首次复制的正式知识库；新电脑的无知识库演示办法见首次配置说明。
- `STACK_PREFLIGHT_OK` 只代表离线检查通过，不代表密钥有效或真实连接成功。

## 4. 排错和开发资料

| 需要做什么 | 看哪里 |
|---|---|
| QQ 首次审批、独立停止、日志和报告 | [M3 操作说明](deep-dive/M3_MANAGEMENT_STACK.md) |
| 正式 Web-only、数据库维护、AI 开关、测试和打包 | [运行与维护参考](deep-dive/BUILD_RUN_REFERENCE.md) |
| 网页操作 | [使用指南](USER_GUIDE.md) |

端口占用先正常停止旧演示，不结束未知 Python 进程。配置缺失、Scope 不匹配或凭据错误时停下核对，不重新初始化已有数据库。
