# Prototype / Management 启动方式比较

2026-10-21 根据两个仓库实际源码调查。调查基线：Prototype `main / 69105f8`，Management `codex/mig3-baseline / 130a150`。本轮只统一 Prototype 页面品牌、文档日常入口，以及给 Management 现有双终端包装层增加显式菜单；未重构启动框架、Simulator 或 AI Runtime。

## 当前实现

| 项目 | Prototype | Management |
|---|---|---|
| 入口 | `scripts/dev/run_local.ps1` → `local_session.py` | 同名入口，另有双击 CMD、Detach 与可选双终端 |
| 顺序 | Web → `/api/bootstrap` 就绪 → Simulator | 同样 Web 优先；交互模式在 Simulator 窗口选择后才运行原生产端 |
| 终端/浏览器 | 两个后台子进程，前台只提示地址 | `-ShowTerminals` 开两个控制台；`-OpenBrowser` 在 Web 就绪后打开网页 |
| 场景 | 六种 `-Scenario`，normal 默认，不读 stdin | 同样六种非交互 CLI；仅显式 `-InteractiveScenario` 读 Simulator 终端输入 |
| 模拟发送 | 原 `apps.simulator`，10秒完整窗口、HTTP JSON v1、一次性环境 Token | 相同，不改发送协议、生成算法、session/sequence 或服务端规则 |
| 数据根 | 无参数为工作区兼容数据；`-DataRoot/-UserData` 可显式选根 | 同样路径解析，另外 `-Demo` 管理独立演示实例和只读知识快照 |
| 初始化 | `apps.management_web --init-data` 必须显式，已有实例拒绝 | 相同；Demo 只在首次安全装配，后续不覆盖编辑 |
| AI/模式 | 启动器默认启用已批准 Qwen Normal/Streaming、多轮、History/统一三工具组合 | 开关合同相同；原 Web CLI 默认 AI/试用关闭，主动发送才联网 |
| 日志/错误 | 后台子进程输出丢弃，启动终端显示地址/安全错误码 | 双终端直接展示 Web 日志和 Simulator 发送结果；隐藏监督进程失败可弹框；非交互后台仍不持久化日志 |
| 占用/停止 | 占用拒绝；Ctrl+C 终止并 wait 自己创建的两子进程 | 同样拒绝占用，双终端另有端口启动锁与 Windows Job Object；关闭任一终端或监督进程退出会回收树 |
| Web-only | 直接 `python -m apps.management_web`，不使用 run_local | 相同；正式实例显式 `--user-data`，不自动开 ingestion |

共同源码入口：`scripts/dev/run_local.ps1`、`scripts/dev/local_session.py`、`apps/management_web/__main__.py`、`apps/simulator/__main__.py` / `scenarios.py` / `transport.py`、`apps/management_paths.py`。Management 专有保护在 `scripts/dev/demo_instance.py`、`windows_job.py`，不得为了同步而移除。

## A. 应统一的用户操作与参数

- 文档最前使用“快速开始 / 常用指令”，明确仓库、数据实例、访问地址和停止方式。
- 保持 `-Scenario/-Port/-Seed/-NoAssistant/-NoStreaming/-NoMultiRound/-NoHistory/-DataRoot` 的共用含义；菜单只作为显式 opt-in，普通 CLI/测试不读输入。
- 页面统一显示“AI 监测系统”，包名、数据库/API 路径和模型发布身份不随品牌变化。
- 端口占用拒绝、只停止自己创建的进程、凭据不打印/复制、启动不主动请求模型是共同要求。

## B. 必须保留的项目差异

- Prototype 保留工作区实验路径和单前台停止习惯；Management 保留独立正式/演示根、知识快照、项目凭据身份、打包和维护配置。两者 `--user-data` 都会指向同一 Windows 正式根，不能因项目不同就当成隔离数据。
- Prototype 目前没有 Job Object 或双终端保证，不宣称强关监督进程也能清理；Management 不能为“脚本一致”降级到该实现。
- 业务数据隔离不等于凭据隔离；不得在同步或演示切换时迁移 Settings、Policy、API Key。Demo 复用已有授权/编辑，新实例仍按既有初始化规则。
- `-NoHistory` 与统一三工具/传输试用联动，不是任意改变已批准 Scope；Policy、Source/Commit Gate 和预算仍由原服务层执行。

## C. 可选择性复用的逻辑

共同的子进程命令组装、就绪检查、一次性 Token、六场景名称和端口拒绝行为可逐函数比较复用，连同离线测试一起合并。未来若 Prototype 也需要双终端，可单独授权迁入 Management 的包装层和 Job/锁测试，不把 Management 的真实数据与凭据身份一起迁入。

本轮菜单复用原 console_role：Web 就绪 → 启动 Simulator 专用终端 → 选择/校验 → 替换原 `--scenario` 参数 → `runpy` 执行原 Simulator。退出返回0，监督进程沿用现有 finally/Job 清理 Web；选前没有创建模拟器实例或发送窗口。浏览器可先打开，此时页面等待模拟数据，属于正常状态。不新增常驻服务、第二套启动器、IPC 或热切换机制。

## D. 无需强行统一的内部实现

不要求两个脚本逐字相同，不迁移 Detach/错误弹窗到无双击需求的 Prototype，不统一 Runtime、安装方式、打包清单和历史文档。隐藏/可见控制台与各项目日志显示方式按真实用途保留；不为外观一致引入通用启动框架。

## 验证与边界

菜单明确维护六场景，测试逐一校验其属于 Simulator 的真实 SCENARIOS；其他 partial/invalid/visual_only/water_only 仍由原 Simulator CLI 用于故障注入，不进入用户菜单。

自动验证只用临时隔离实例、虚构知识/凭据与 Fake SDK。菜单数字/默认/无效/退出先在原控制台包装层 dry-run 验证，再检查真实双终端等待期间不上报、取消后回收、选择后上报及重启保留历史/新增 session。不得通过清空演示历史实现切换；设备离线场景到30秒后停止上报，是场景语义，不表示网络故障。

开发流程保持：Prototype 实验 → 测试 → 人工审核 → 选择性同步 Management → Management 独立回归；不混用 Git 历史，不自动 commit/push。

### 本轮验证结果

- Management 启动/菜单/演示隔离/HTTP 专项共30项 Python 通过（106.767秒）；两仓库各96项 Node 全过，Prototype HTTP专项11项通过。本轮未重跑未修改的完整 Backend，未调用真实 Provider/NPU。
- 菜单六场景均由原 console_role 包装层执行真实 Simulator dry-run；Enter默认、非法输入重试、0/7/EOF取消均已覆盖。Windows 隔离实例实测等待超过10秒仍无批次，关闭任一终端均回收；输入0后 Web/Simulator退出且无上报；无效输入后 Enter、随后重启选择低氧均正常，旧批次保留、session不同且新sequence从0开始。
- 原非交互场景与10秒 HTTP上报、双终端连续启动、占用拒绝、强制结束监督进程的回收继续通过。演示副本测试使用虚构正式知识源，验证复用保留知识编辑、Settings和Policy；三工具用Fake SDK，不读取用户真实32条知识或凭据。
- Prototype 1440px桌面与390px侧栏展开检查通过，品牌不裁切，页面无横向溢出；浏览器标题与底部名称一致。截图在该仓库 Git 忽略的 `apps/management_web/tests/outputs/launch-brand/`。
- 启动测试初次遇到测试辅助读取连接未关闭导致临时库清理失败，已使用显式关闭修正并重跑通过；没有修改业务数据库连接逻辑。

最终人工验收：双击 Management 入口，查看菜单与两窗口使用体验；确认 Prototype 品牌与两份快速入口是否符合日常习惯。当前演示库和正式数据没有为本轮验证启动或写入。

### 改动清单

以下均相对各自仓库根，未跨仓库整文件覆盖：

| 仓库 | 文件 | 作用 |
|---|---|---|
| Prototype | `apps/management_web/static/index.html`、`app.js`、`styles.css` | 左上角、静态/动态标题及底部品牌；复用 Management 已验证的品牌宽度与 Logo 不收缩样式 |
| Prototype | `apps/management_web/tests/test_app.py`、`monitoring-ui.test.mjs` | 品牌 HTML/资产与页面标题回归 |
| Prototype | `apps/docs/BUILD_RUN.md`、`ROADMAP.md` | 快速入口与完成记录，保留详细阶段资料 |
| Management | `scripts/dev/local_session.py`、`run_local.ps1`、`启动演示系统.cmd` | 菜单、显式交互参数和双击入口 opt-in；原非交互 CLI 默认不变 |
| Management | `apps/management_web/tests/test_scenario_menu.py`、`test_windows_demo_lifecycle.py` | 六场景 dry-run/输入/参数兼容与真实隔离双终端生命周期 |
| Management | `apps/docs/BUILD_RUN.md`、`README.md`、`ROADMAP.md`、`STRUCTURE.md`、`deep-dive/LAUNCHER_COMPARISON.md` | 快速入口、差异调查、测试与目录说明 |
