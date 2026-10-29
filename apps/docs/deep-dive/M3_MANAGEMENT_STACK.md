# M3：独立 QQ Hybrid Bot 与三终端启动

2026-10-29，Management 源码工作区。基线 `codex/mig3-baseline / 9d24d632f30624c6646b9d186ef7147c4bf9cb37`（M2 已提交、开始时干净）。本阶段只进行离线/Mock/Windows 本机验收，没有连接真实 QQ/Qwen，没有读取真实凭据或正式数据库，也未改 Prototype。

## 1. 快速使用：先验收纯离线三终端

在 **Management 根目录**的普通 PowerShell 执行。Python 使用本项目 `.venv`；脚本兼容 Windows PowerShell 5.1，保留 UTF-8 BOM。

先创建全新的隔离实例和配置。目标目录若已存在会拒绝，绝不会覆盖；需用新的名称或明确使用先前已生成的 request。此命令只生成 SIMULATOR 数据，空 Knowledge 为 Web 初始化要求，不复制演示知识库或凭据。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_Management'
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli prepare-demo --data-root D:\CodexProject\Fishery_Management\outputs\qq-m3-instance --config-directory D:\CodexProject\Fishery_Management\outputs\qq-m3-config --enable-ai
```

检查与启动各一条命令：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -Request .\outputs\qq-m3-config\request.json -WithBot -OfflineDemo -Check
.\scripts\dev\Start-ManagementStack.ps1 -Request .\outputs\qq-m3-config\request.json -WithBot -OfflineDemo -RunSeconds 60 -NoAssistant
```

预期打开 Simulator、Web、Bot 三个独立窗口。Bot 使用 Fake Gateway + Mock Provider，自动确认的是**纯离线测试许可**，不能转换为联网许可。虚构成员自动发一条水质问题；不向 QQ 发消息、不调用模型。Web 地址默认为 `http://127.0.0.1:8766`，Simulator 按原方式每 10 秒上报。

`-NoAssistant` 只用于本次离线 Web 验收；正式手工启动可省略以沿用原 Web Assistant 启动参数。原 Web 不会因为启动而自动调用模型。

`-RunSeconds` 只缩短 Bot 的本次运行，不延长已批准期限；Bot 到期后 Web/Simulator 继续运行。结束整个三终端请用编排终端 Ctrl+C 或停止脚本。

## 2. 选择启动范围

| 操作 | 命令/参数 |
| --- | --- |
| 只启动 Web+Simulator，Bot 默认不启动 | `Start-ManagementStack.ps1 -DataRoot <M3隔离实例路径> -NoBot` |
| 三终端 Fake 验收 | `Start-ManagementStack.ps1 -Request <request.json> -WithBot -OfflineDemo` |
| 仅检查独立 Bot | `Start-QQBot.ps1 -Request <request.json> -Check`，Fake 检查加 `-OfflineDemo` |
| 独立启动 Bot | `Start-QQBot.ps1 -Request <request.json> -Run`，第三终端内审批 |
| 实际三终端 | `Start-ManagementStack.ps1 -Request <request.json> -WithBot`，Bot 终端内审批 |
| 仅停 Bot | `Stop-QQBot.ps1 -RunDirectory <STACK_STARTING输出的目录>` |
| 停整个新 Stack | `Stop-ManagementStack.ps1 -RunDirectory <同一目录>`，或在编排终端 Ctrl+C |

启动脚本不是默认联网开关。必须同时具备 `-WithBot`/独立 `-Run`、有效且 enabled 的本机配置、精确 Scope、当前进程许可和人工批准。`Start-QQBot.ps1` 不带 `-Run` 时只 Check；旧 `python -m apps.qq_bot --check` 仍返回默认禁用。

原 `run_local.ps1`、`local_session.py`、双击演示入口及 Web/Simulator 默认参数不改。原有实例继续用其原入口。本次新的 Stack 只接受有 M3 初始化标记的新隔离实例，不能拿正式库或 `outputs/demo-instance` 直接试运行。

## 3. 用户亲自批准真实 QQ/Qwen 前

以下是操作说明，Codex 本轮没有执行真实 Run。

1. 安装可选 QQ 依赖。Web 原依赖不变，M3 固定使用已核对接口的 `websockets==15.0.1`；缺失或其他版本在 Check 时明确拒绝。

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[qq]'
```

2. 用真实 AppID、批准的测试群/成员 OpenID 创建**另一组全新隔离配置**。元数据不是密钥，但不要把完整 OpenID/配置贴入聊天或公开日志。最多显式选择四人，多写几次 `--member` 即可；共享整个 Run 额度。

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli prepare-demo --data-root D:\CodexProject\Fishery_Management\outputs\qq-m3-real-test --config-directory D:\CodexProject\Fishery_Management\outputs\qq-m3-real-config --app-id '你的AppID' --group-id '批准的群OpenID' --member '批准的成员OpenID' --enable-ai
```

3. Management 已通过其 Web 保存的 DashScope Key，可复用相同 Management 私有 Store。不会读取或迁移 Prototype 的密钥。QQ AppSecret 使用下列独立命令，在本机隐藏输入；不放命令行/项目配置。已有 QQ 密钥确需替换时才加 `--replace`。

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli save-secret
```

该命令复用原 CredentialStore/ProjectEnvWriter，引用 `FISHERY_QQ_APP_SECRET`；保留其他 Key。不存在 DashScope Key 时，先在 Management 原 Web Settings 按既有流程配置，不复制 Prototype 私有文件。

4. 执行真实模式 Check；不解析密钥，不打开 Monitoring SQLite，不联网、不创建批准。

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -Request .\outputs\qq-m3-real-config\request.json -WithBot -Check
```

5. 人工复核本机配置中的群/成员、SIMULATOR 数据披露及预算，然后执行启动命令：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -Request .\outputs\qq-m3-real-config\request.json -WithBot
```

在 **Bot 专用终端**查看模型、实例、设备、Scope、群/成员摘要和费用风险，输入本次显示的 `APPROVE MANAGEMENT <12位摘要>`。没有自动审批参数。拒绝/关闭审批窗口时，Bot 不联网，Web/Simulator 可继续运行。终端中的群/成员使用摘要，完整身份以预先核对的本机 `access.json` 为准。

6. QQ Gateway READY 后，授权成员分别测试：`@机器人 你好`、`@机器人 什么是溶解氧？`、`@机器人 现在水质怎么样？`、`@机器人 那溶解氧呢？`、`@机器人 /清空会话`。固定查询仍支持 `/当前水质`、`/帮助`；其他固定查询/写操作未开放。

每次代码/依赖/Scope/权限变化都会使旧配置或许可失效。重新审阅后创建新 request/新 Run，不编辑旧 approval、used 或历史报告来续额度；不要重新初始化既有业务库。

## 4. 配置与批准合同

生成目录包含 `request.json`、`access.json`、`ai.json`、`monitoring.json`、独立 `policy/`。源码中的 [request 示例](../../qq_bot/examples/request.example.json)、[访问示例](../../qq_bot/examples/access.example.json)、[AI 示例](../../qq_bot/examples/ai.example.json)、[实例示例](../../qq_bot/examples/monitoring.example.json) 仅说明格式，不能直接作为已批准配置。正常使用初始化命令生成正确的 Scope 摘要。

`request.enabled` 默认 false；`--enable-ai` 明确打开运行准备开关。`ai.json` 中的 enabled/工具 grant 是本机渠道权限准备，不等于联网批准。缺少本进程 RunConsent 时仍不能创建真实 I/O。

真实合同独立为 `management-qq-hybrid-process-run@1`。准备资源保持 candidate、qualification_id=null；不是 released，不是把 M2 Fake candidate 布尔值改为 true。人工审批后才产生本进程 `LivePermit`；它绑定原 RunLedger/TurnLease、当前 Scope、权限、实例、设备、成员和进程 nonce，不能从 JSON 或 QQ 正文反序列化取得。

首版限制：1800 秒、5 Turn、2 请求/Turn、512 输出 Token/请求、90 秒/Turn、零重试，1 worker+2 等待。每 Turn 预留 1.602765 元，五轮至少 8.013825 元（默认批准上限 8.02 元）。General 通常 1 请求，仍完整预留；失败、取消及未知送达不退款，清空记忆不恢复额度。本地费用预留不是云平台账单硬上限。

真正的配置/Scope/Policy/SDK/所有权复核仍发生在准入、Tool、模型 I/O、发送和历史提交等边界。每轮私有 Service/Handle，原 Agent SINGLE_ROUND 不变。General/Water 仍分别使用 @2 General 防护、原封闭水质解释；没有 Knowledge/历史 Tool、ACK、人工处理或设备控制。

准备 Scope SHA256：`3e3861d4acb371d110d81cd4c8e0a3d7c71c782ceeb54ccd09280c6f5c0b9494`。M2 Fake candidate 已按共享文件变化刷新为 `3604a41b082ee2dad348fe02445602c8474a86fc34ec18ad208d7d6a64526693`；旧 Scope/批准不可代用。没有修改旧批准、used 或 Provider 回执。

RAM 历史继续隔离群/成员/实例/设备/权限；仅 QQ API 明确接受后提交安全文本/哈希。未知交付不重发、不重新推理、不提交成功记忆；退出清空。报告的 API 接受不能自动当作客户端显示确认，用户需在 QQ 客户端另外确认。

## 5. 三进程生命周期、日志与停止

统一编排调用原 `local_session.run_local()`，通过其 launch/sleep 接口包装控制台与日志；未复制 Web/Simulator 命令构建或修改旧默认。原配对进程关闭规则保留：关闭 Web/Simulator 任一窗口会结束这次配对；新编排随后清理自己的 Bot。**关闭 Bot 只结束 Bot**，不会退出配对循环。

每次启动创建 `outputs/management-stack/stack-<随机ID>/`，终端第一条 `STACK_STARTING` 输出精确路径。

| 文件 | 内容 |
| --- | --- |
| `stack.json` | 控制进程 PID、nonce、模式和本机选定实例 |
| `web.log` / `simulator.log` / `bot.log` | 各终端独立日志；Bot 只输出安全状态/Usage/摘要，不输出聊天正文、Key/Token 或完整 OpenID |
| `<role>.status.json` | 服务实际 Python PID、独立 console handle、状态、日志、退出码 |
| `controller.log` | 各服务状态变化、审批等待、失败/退出，不把创建窗口当作 READY |
| `bot-run/` | 本进程批准摘要、不可复用 used、写前额度日志、交付检查点、逐轮及最终结果 |
| `result.json` | 整体和各服务实际 PID/退出码，Bot 失败反映为非零/未全部成功 |

Bot 使用独立、当前进程批准与独占 Bot 锁；实例写服务采用单独锁。M3 标记的实例额外在 Web CLI 生命周期持锁，阻止旧 Web 入口换端口重复打开同一 M3 实例。普通旧实例没有标记，不新增此限制，也不依赖 qq_bot。

停止脚本只给本次 nonce 写停止请求，不搜索或结束所有 Python。正常停止先取消/关闭并保存报告；不合作/审批输入阻塞时，启动器在有界等待后只终止自己创建的命名 Job。窗口关闭/崩溃也会由所属 Job 回收后代。无自动重启、旧消息重放、余额恢复。

强制关闭终端或杀进程无法保证最后一份 Bot 报告落盘；保留已有 fsync 额度/交付检查点，控制日志报告退出码/报告不完整，不据此重试。SDK 不合作线程及远端计费未知仍是剩余风险；隔离不清零。Web 与 Bot 的 SDK 全局资源对象在不同进程，不共享隔离状态。

## 6. 实现文件与发行

- `ai_service/channel_management_live.py`：独立 Scope、进程许可、逐轮授权及真实 SDK I/O 工厂；复用 M1 Adapter/资源门禁，不复制 Agent。
- `qq_bot/management_config.py`、`management_run.py`、`management_cli.py`：明确配置、新建隔离实例、Check、人工审批、运行与报告。
- `qq_bot/live_transport.py`：许可限定的 HTTPS/WSS/被动交付；原 M2 默认连接器仍禁用。
- `qq_bot/demo_runtime.py`：纯离线 Fake 帧和 Mock SDK，仅显式 `-OfflineDemo` 使用，不是失败 fallback。
- `scripts/dev/management_stack.py`、`stack_console.py`、`console_job.py` 与四个 Start/Stop PS 脚本：原配对启动的薄编排、日志、Job 及停止。
- `apps/management_process.py`、Web CLI 的小型生命周期包装：仅 M3 标记实例的写服务锁；原实例无标记时不加锁，不导入 Bot。
- 原 Service/Coordinator/Scheduler/Delivery/Router/Gateway 只加入精确的新类型分支；旧 Web、M2 Fake/普通 QQ CLI 语义不变。旧 SDK Backend、Monitoring 规则/Schema、Tool 定义、原 PowerShell/双击启动器保持原样。
- 发行 staging 通过显式白名单携带上述启动器及旧依赖，不带研究/测试脚本、配置实例、密钥或报告；Wheel 包含独立运行模块，源码/staging 提供 Windows 终端脚本。Runtime Scope 绑定应用内真实授权/SDK/工具代码，启动脚本另列发行文件摘要，脚本本身不能制造许可。

## 7. 验证与已知限制

| 验证 | 结果 |
| --- | --- |
| M2 已验收基线 | 715 Python / 116 Node |
| 首轮 M3 完整回归 | 735/735 Python，388.627 秒；116/116 Node |
| 补跨入口保护后的最终完整回归 | **736/736 Python，456.114 秒；116/116 Node，无跳过** |
| M3 核心与 Windows 专项 | 前期专项 19/19；最终新增总计 21 项，全部纳入全量 |
| 最终启动/跨入口/发行 staging 专项 | 7/7 通过 |
| 白名单 staging、Wheel 构建、新进程导入/Scope | 通过，含配置示例及独立 Management 模块，无业务库/凭据 |
| Python 语法、文档链接、PowerShell 5.1/BOM、git diff --check | 通过 |

命令：`.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/run_management_tests.py --verbose`。原有测试未删除、未跳过、未弱化。

已专项覆盖：General/Water/混合五轮、实际 Mock HTTP 计数、拒批零请求、scope/预算/缺库、撤权/到期、普通失败后的新消息、未知交付、报告失败、真实 SDK/连接器构造但全为内存 HTTP/Fake WSS；三个独立 PID/console handle、停止/崩溃、SDK 隔离后原配对持续入库、端口/实例重复拒绝及无关进程存活、PowerShell 5.1 Check。

非敏感测试证据：`outputs/test-tmp/m3-20261029/`。中间失败日志保留；包括测试夹具最初阻断 asyncio 私有唤醒 socket，以及子进程故障注入过早替换 Popen 导致 asyncio 导入失败。修正的是夹具，未放宽真实网络/资源门禁。

本轮不会自动读取或修改正式 `%LOCALAPPDATA%/FisheryManagement`、已有 `outputs/demo-instance`，也不会迁移任何凭据/真实记录。不修改 Monitoring v2 Schema，没有增加人工审核功能。真实传感器或正式实例须另行设计并授权，不能简单复制 M3 标记来冒充隔离实例；本机锁和标记不是针对同 Windows 用户/管理员篡改的安全边界。

后续用户真实验收独立记录：Gateway READY、General/Water 实际请求/Tool、SDK CLOSED、QQ API 接受、History Commit、客户端显示、停止和最终报告。离线通过不等于上述真实验收已完成。

Check 有意不验证密钥是否存在/有效，也不验证真实平台成员权限、网络可达性或模型效果。缺钥、失效或拒绝时真实运行会安全失败；已准入 Turn 按合同保守消耗，不能靠自动重试解决。由用户完成真实测试前须在本机核对这些前置项。

最终 Git：HEAD 保持 `9d24d63`，本轮变更全部未暂存、未提交，完整路径/摘要清单见 `outputs/test-tmp/m3-20261029/final-files.json`。原 Backend、Monitoring/Schema/规则、Knowledge、Simulator、旧启动器未变；Prototype 工作树保持不变。唯一新增可选包为本项目 `.venv` 的 websockets 15.0.1，原 SDK/httpx 未升级。启动器及软件版本摘要见同目录 `final-launchers.json`、`environment-and-package.json`；最终全量日志为 `management-verified.log`。本轮到此停止。

官方接口核验：继续使用 [QQ GET /gateway](https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html)、[接口调用与鉴权](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html)（页面更新 2026-07-30，本轮核验 2026-10-29）及 [websockets 15 同步客户端](https://websockets.readthedocs.io/en/15.0/reference/sync/client.html)。Token 入口仍为 api.bot.qq.com/app/getAppAccessToken，REST 固定 api.bot.qq.com；WSS 精确白名单保留 api.bot.qq.com / api.sgroup.qq.com，TLS 验证、无代理/重定向、端口/路径及参数限制保持。
