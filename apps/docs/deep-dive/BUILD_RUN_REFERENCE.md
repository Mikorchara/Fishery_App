# 运行与维护参考

日常演示只需 [BUILD_RUN](../BUILD_RUN.md) 的两个入口。本页保留正式实例、数据保护、AI 开关、测试与打包的详细说明；不是组员首次启动前必须逐条执行的清单。QQ 专用审批与日志见 [M3](M3_MANAGEMENT_STACK.md)。

## 数据库兼容与人工结束

维护记录显示正式及演示Monitoring已于2026-10-23按用户批准升级v2。本次人工结束功能继续使用v2，不需要再次升级或初始化；其他尚为v1的旧实例仍须单独批准维护，不会自动升级。

事件详情新增“人工结束此风险”：仅对因失联、过期、缺测等原因待核实的风险，填写原因并确认后结束提醒，原监测事实和操作历史保留；再次可靠检出会重新提醒。没有记录时，可按[虚构预览步骤](EVENT_MANUAL_END.md#验证与人工预览)体验，完全不使用正式或演示数据库。

## 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'setuptools>=68' -e .
.\.venv\Scripts\python.exe -m pip check
```

安装依赖可能访问 Python 包索引，不请求 LLM。开发环境只允许本项目自己的 editable 安装。

## 双击演示：两个终端 + 独立知识副本

双击操作与场景菜单见上方快速入口。该入口可从任意工作目录启动，复用 `run_local.ps1` 并自动定位 `.venv`；Web 先就绪，再由 Simulator 窗口选场景，之后每10秒更新水质和视觉统计。重复启动遇到端口占用会拒绝，不结束其他进程。

首次使用在 `outputs/demo-instance` 建立独立的空 Monitoring，通过 SQLite Backup API **只读复制** `%LOCALAPPDATA%\FisheryManagement\knowledge.sqlite3` 的完整知识记录、版本、状态、来源与迁移标记。正式知识库须正常关闭、无 SQLite 日志或写入连接；忙碌/缺失/不兼容时明确报错，不建立空白替代库。当前正式库为32条，但启动器不写死条数。

不复制正式 Monitoring、Settings、Policy、Credential 或 Trace。新演示实例通过现有 Policy Store 建立三工具授权；模型仍为已有 Qwen Normal / Streaming `local_experimental` 范围。以后启动直接复用演示知识、设置和授权，不读取正式源、不重置编辑；若已有实例知识为空或缺库，明确停止等待人工核对，不覆盖或重建。

排错时在项目根用前台命令查看具体原因：

```powershell
.\scripts\dev\run_local.ps1 -Demo -ShowTerminals -InteractiveScenario -OpenBrowser
# 只演示监测，不装配 AI / 私有凭据
.\scripts\dev\run_local.ps1 -Demo -ShowTerminals -NoAssistant
```

端口可用 `-Port 8767` 改变；两个窗口标题会显示所选端口。Windows 无法提供进程组回收保护时拒绝启动。`.ps1` 保留 UTF-8 BOM 兼容 Windows PowerShell 5.1；不更改执行策略或申请管理员权限。双击启动失败会显示提示，按上述前台命令可查看错误代码。菜单是本次启动选择，不在运行中热切换；交互模式下菜单选择覆盖 `-Scenario`，Enter 始终为 normal。

**业务数据隔离不等于凭据隔离。** 演示 AI 使用当前新项目已有的私有 Credential Store，不复制或新建密钥；启动、打开页面不调用模型，用户点击发送/测试连接仍可能计费。自动验证只用虚构凭据、Fake SDK 和隔离实例。演示内保存的偏好/预算属于演示 Settings，不继承正式 Settings；修改密钥属于项目私有凭据操作，不能当作演示数据编辑。

## 正式用户实例：只启动 Web

先进入 `D:\CodexProject\Fishery_Management`，使用已迁移实例：

```powershell
.\.venv\Scripts\python.exe -I -B -m apps.management_web --project-root "$PWD" --user-data --enable-assistant --assistant-multi-round-trial --assistant-streaming-trial --assistant-history-trial --assistant-tools-trial
```

访问 http://127.0.0.1:8766 ，Ctrl+C 停止。此命令不启动 Simulator、不启用 ingestion；读取已有监测数据，允许用户按网页功能编辑知识、保存设置或主动请求模型。初始模式默认为 Normal，已保存偏好可以覆盖；启动、页面加载和模式切换不自动请求模型。工具仍需用户 Policy 授权，凭据须可用。

关闭 Streaming：停止后去掉 `--assistant-streaming-trial` 重启。关闭全部 AI：仅保留 `--project-root "$PWD" --user-data`；不删除数据、设置或授权。端口冲突时使用 `--port 8767`，不要杀掉未知进程。

## 隔离实例与一行模拟联调

以下仅用于建立新的开发实例，不导入或覆盖正式数据（目标必须不存在，父目录必须存在）：

```powershell
New-Item -ItemType Directory -Path outputs -Force | Out-Null
.\.venv\Scripts\python.exe -I -B -m apps.management_web --project-root "$PWD" --data-root "$PWD\outputs\dev-instance" --init-data
```

初始化只建立空白 Monitoring/Knowledge 和必要目录，不导入旧知识、监测数据、设置、Policy 或密钥，不启动服务。已有实例缺库、损坏、Schema不兼容均应报错，不能靠初始化掩盖遗漏。

后续一行启动 Web、AI 本地试用和 Simulator：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\dev-instance"
```

访问 http://127.0.0.1:8766 。Ctrl+C 停止自己启动的服务器和模拟器。启动器生成一次性 HTTP 接入 Token，不输出/保存；每10秒上报，数据明确为 simulator。端口占用拒绝，不终止未知进程。-Port 可另选端口；-Scenario 支持 normal、low_oxygen、suspected_disease、reduced_feeding、combined_anomaly、device_offline。

**启动器没有只启动 Web 的选项，始终启动 Simulator 并写入所选实例。** 不要把 `-DataRoot` 换成 `-UserData` 作为日常操作：那会写入正式监测数据库，并受历史留存上限影响。正式实例的 Web-only 命令见上一节。开发端口也可用 `-Port 8767`。

增加 `-NoAssistant` 可只演示模拟监测，不装配 AI / 私有凭据；仍会写入隔离实例。隔离数据根不隔离凭据：启用 AI 的手动联调仍使用当前项目 Credential Store，发送可能计费；只有自动离线测试使用 Fake SDK。正常联调启动本身不请求模型，真实对话由用户主动发送。

原服务器 CLI 默认关闭 AI 与试用开关；一行启动器默认启用已有批准的 Qwen 范围，保留 `-NoStreaming`、`-NoHistory`、`-NoMultiRound` 关闭选项。其中 `-NoHistory` 也使启动器不传三工具统一开关，不能理解为仅从任意已发布组合中删一个 Tool；工具独立启停请用设置中的 Policy。不要省略数据根参数使用历史兼容路径。

## 数据路径、凭据与初始化保护

数据位置集中在 `apps/management_paths.py`。`--data-root/-DataRoot` 是绝对路径；`--user-data/-UserData` 指向已迁移的 `%LOCALAPPDATA%\FisheryManagement`。两个 SQLite、Settings、管理 Policy/同根共享兼容 Policy、Trace 都属于选定实例，不向源仓库回退。省略所有路径参数仍保留仓库相对兼容默认，不能据此自动发现正式数据。

显式实例的 Monitoring / Knowledge 都须先通过缺失、完整性与 Schema 检查，才构造写入服务。`--init-data` 只用于新实例；对已有正式实例报错应核对路径和备份，不能用空白初始化代替迁移或恢复。

Credentials 保持独立私有 Store，`PROCESS_ENV > PROJECT_ENV > MISSING`。Windows 路径为 `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<项目根身份摘要>\credentials\.env`；历史父目录名不是旧 Runtime 依赖。项目根变化会改变身份，不自动读取源项目 Key。用户已确认 MIG-5 凭据及网页基本验收；本次文档整理不读 Key 或重新测试。不要复制 `.env`，不把密钥放进业务数据、Git、URL、浏览器存储或聊天。变更密钥使用设置页“测试新密钥 → 保存”，由用户主动进行，测试可能计费。

备份区别及知识库 Backup API 命令见 [使用指南](../USER_GUIDE.md)。MIG-4 备份是一次性迁移基线，不是自动日常备份，不应清理或反复执行迁移。执行回执见 [MIG-4](MIG4_DATA_MIGRATION.md)。

## 离线测试

```powershell
.\.venv\Scripts\python.exe -I -B scripts/dev/run_management_tests.py
.\.venv\Scripts\python.exe -I -B scripts/dev/run_tests.py fast
```

完整入口覆盖 Backend、业务 Assistant、三个 Tool、Monitoring、Simulator、Knowledge、管理 HTTP/SSE、Settings 和 Node；阻断 fishery_ai 导入。TEMP/TMP 自动定位 outputs/test-tmp。人工资格不混入自动回归，不自动发真实请求。

专项直接调用 unittest 时，也应把 TEMP/TMP 指向本项目 outputs/test-tmp；使用虚构凭据和隔离数据，不要运行旧混合工程的 PRODUCT/QUALIFICATION 选择项。本仓库 run_tests 的 management 与 management-independent 都是完整管理集，fast 是管理专项小集合。

事件状态、三窗恢复、等级关联、时间筛选和历史硬删除的验收边界见 [事件管理](EVENT_MANAGEMENT.md)。离线完整入口包含事件专项；删除验证只能使用临时数据库，不能针对正式或既有演示实例。

## Wheel

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir outputs/dist .
```

需预先安装 setuptools>=68，不能降低 build-system 要求。发行包只含 apps 程序、固定 JSON 和静态资源，不含 tests、development、SQLite、Settings、Credentials、Trace、缓存、文档或运行输出。Python依赖约束与来源版本一致。MIG-2 staging 生成器保留作工程检查；本项目正式构建直接使用根 pyproject。

## 设置与 AI

系统设置可管理默认模型/设备/模式、Tool 授权、用户主动连接测试与受控预算。当前/历史/Knowledge 来源独立，Qwen 三工具 Normal/Streaming 为 `local_experimental`，不因迁移升级为 `released`。未保存偏好时默认 Normal，最多 2 Calls/2 Rounds/3 Requests、每轮最多一个 Tool、retry=0、120秒。统一范围默认 Normal 1024 / Streaming 512 tokens/请求；满足已批准条件时可各自保存 1～4096 整数，实际值以网页为准。其他模型不继承该范围。

Preview 未通过 Commit Gate 不进入成功 History；Stop、断流、超时和失败不重试、不切换模式/Provider。主动点击发送只授权当前冻结配置；配置改变使旧 revision 失效。完整合同见 INTEGRATION 与开发指南。

## 真实测试

`scripts/manual_real_tests/` 只委托现有管理资格 CLI，默认 dry-run；真实执行需具体计划与次数批准。网页发送和密钥测试则由用户点击明确发起。文档核对不代替真实验收，也不授予新模型资格。历史操作记录在 history/，不作为新项目启动前提。

### 新场景：快速下降后逐步回升

批准升级后，可在演示菜单选7，或在已初始化的隔离 v2 实例使用：

```powershell
.\scripts\dev\run_local.ps1 -Scenario oxygen_drop_recovery -DataRoot "$PWD\outputs\dev-instance"
```

0–20秒约6.4mg/L；20–50秒快速降至2.2；50–90秒低氧保持；90–180秒升至4.2；180–300秒继续升至6.4，此后保持正常、不重复。原生成器仍叠加波动并按窗口求均值；事件由 Monitoring 原规则判断。Prototype 没有交互菜单，Management 菜单仍复用原启动器。只生成不上报：`.\.venv\Scripts\python.exe -I -B -m apps.simulator --scenario oxygen_drop_recovery --seed 42 --windows 36 --dry-run`。
