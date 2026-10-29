# 独立管理项目结构

本页提供两个版本：**简略版**用于快速了解分层；**详细版**用于按文件查找实现和交接职责。

详细版逐一列出当前 Git 跟踪的源码、固定资源、测试、脚本和文档。`.git/`、`.venv/`、缓存、运行产物、真实数据库、Settings、Policy、Trace 和凭据不逐文件展开，也不读取其内容。路径相对项目根 `D:\CodexProject\Fishery_Management`；详细表中的文件名相对各表标题所示目录。

## 一、简略版：先看项目分层

```text
Fishery_Management/
├── pyproject.toml                 # 独立 management 发行，不包含旧包
├── README.md / AGENTS.md / .gitignore
├── apps/
│   ├── management_paths.py        # 唯一业务数据路径装配
│   ├── management_web/            # Flask HTTP/SSE、访问控制、UI、测试
│   │   ├── __main__.py / instance.py
│   │   ├── ai_adapter.py / settings_api.py / streaming.py
│   │   └── static/                # 无 npm 构建的 HTML/CSS/JS
│   ├── ai_service/                # 业务配置、设备/Policy冻结、来源/提交
│   │   ├── service.py / execution.py / streaming.py
│   │   ├── settings.py / settings_store.py / management_policy.py
│   │   ├── business_tools/        # Current / History / Knowledge，显式 Registry
│   │   ├── runtime/               # 业务 Assistant、Prompt、Receipt/Ledger
│   │   ├── resources/             # 固定 Scope/Release/Candidate，全部保留
│   │   ├── development/           # 仅源码人工资格，默认dry-run，不进Wheel
│   │   └── tests/                 # 新侧回归、Fake SDK用例、固定指纹
│   ├── ai_backend/                # 通用 Gateway/Adapter/Tool循环/Streaming/请求
│   ├── qq_bot/                    # M2独立进程候选；Fake Hybrid/只读实例/额度与会话；默认禁网
│   ├── monitoring/                # 事实、规则、Events、SQLite、历史统计
│   ├── knowledge/                 # 内容 CRUD、SQLite、TF-IDF、显式迁移
│   ├── simulator/                 # Scenario、10秒采样窗口、HTTP上报
│   └── docs/                      # 当前操作、开发合同与历史设计
├── scripts/
│   ├── dev/                       # 双击演示、双终端启动、独立离线测试
│   ├── maintenance/               # 受控数据迁移维护，非日常启动
│   ├── packaging/                 # MIG-2发行模板/白名单staging检查
│   ├── qualification/             # 管理专用显式资格CLI
│   └── manual_real_tests/          # 用户主动真实测试，默认dry-run
├── .venv/                         # 忽略，本项目独立环境
└── outputs/                       # 忽略，演示与隔离实例/测试/构建/报告
```

管理依赖为 Web → AI service → Backend；AI service 的业务 Handler 查询同一 Monitoring / Knowledge 服务。Monitoring 不依赖 AI；Backend 不依赖 Flask、SQLite 或业务模块。执行循环不复制。

正式用户实例已迁移，显式 `--user-data` 使用 `%LOCALAPPDATA%\FisheryManagement`；开发用 `--data-root` 指向隔离实例。代码为兼容旧合同保留仓库相对默认路径，日常不要省略数据根参数。凭据使用独立私有 Store，不在业务实例根。没有 src/fishery_ai、旧根 tests 或旧 outputs 运行依赖。知识固定 JSON 仅为测试与资格夹具，正式内容唯一权威为所选实例 knowledge.sqlite3。

用户操作与数据位置见 [使用指南](USER_GUIDE.md)；Tool、Prompt、Scope 和安全边界见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。当前工程命令见 [BUILD_RUN](BUILD_RUN.md)；旧目录地图存于 history/，只是来源记录。

当前双击入口是 `scripts/dev/启动演示系统.cmd`，演示实例位于 `outputs/demo-instance`。首次只读复制正式知识，后续保留演示编辑。演示业务数据隔离不等于项目凭据隔离。

当前视频页展示模拟视觉统计，没有真实视频流、摄像头或 NPU 接入。各层 `streaming.py` 处理 LLM Streaming，不是视频推流。

## 二、详细版：逐文件职责

阅读提示：`tests/` 是离线回归与夹具，不是业务启动入口；`development/` 和资格脚本是显式开发工具，不因文件存在而获得真实调用授权。`resources/` 是固定发布/协议配置，不是用户数据。`research/` 和 `history/` 包含当时的设计与快照，当前行为以实际源码和操作文档为准。


### 2.1 项目根目录 — `./`

| 文件 | 功能简介 |
|---|---|
| `.gitignore` | 排除虚拟环境、业务数据、数据库、凭据、日志、模型权重及构建缓存，防止进入 Git。 |
| `AGENTS.md` | 本仓库开发规则，约束依赖方向、真实数据与密钥保护、离线测试及提交。 |
| `README.md` | 项目总入口，介绍独立应用、安装、正式实例启动和主要文档。 |
| `pyproject.toml` | Python 发行元数据、依赖、包发现与固定资源白名单；排除测试、development 和业务数据。 |

### 2.2 应用公共入口 — `apps/`

| 文件 | 功能简介 |
|---|---|
| `AGENTS.md` | 应用层详细架构规范，定义 Web、AI service、Backend、Monitoring 和 Knowledge 的职责边界。 |
| `__init__.py` | 应用包标识；导入时不启动服务或装配 Runtime。 |
| `management_paths.py` | ManagementPaths.resolve() 统一解析 Monitoring、Knowledge、Settings、Policy 和 Trace 路径，不读数据或密钥。 |

### 2.3 Web 后端 — `apps/management_web/`

| 文件 | 功能简介 |
|---|---|
| `README.md` | 管理 Web 模块说明与使用入口。 |
| `__init__.py` | Web 包标识；实际服务由显式入口启动。 |
| `__main__.py` | python -m apps.management_web 入口；解析实例、端口、数据接入和 AI 开关，校验已有库并装配服务。 |
| `app.py` | Flask create_app()、Host/Origin 保护、安全响应头、数据上报、监测/事件、AI 请求与取消路由。 |
| `event_api.py` | 本机事件维护能力令牌、严格请求校验及已恢复历史的预览/删除 HTTP 入口。 |
| `contracts.py` | Web 消费的监测、AI、视频展示、资料与事件服务 Protocol；监测事实复用公共合同。 |
| `ai_adapter.py` | 将业务 Assistant 接到 Web，管理浏览器 Token、请求控制句柄及 Normal/Streaming 准备。 |
| `instance.py` | 显式初始化空实例，检查路径、SQLite 完整性和 Schema；已有实例缺库时拒绝静默建库。 |
| `knowledge_api.py` | 本机知识 CRUD、状态、检索和导出 HTTP 接口，包含写入 Token 与输入校验。 |
| `settings_api.py` | 偏好、预算、凭据测试/保存等设置 HTTP 边界，复用 Assistant 浏览器授权。 |
| `services.py` | 早期静态 Demo 适配器与未接入服务占位，不是实际采集器、视频服务或真实 AI。 |
| `streaming.py` | 将单次 Assistant 执行转为 POST SSE，处理预览、终态、断流与资源收尾；不是视频推流。 |
| `package.json` | 声明前端为 ES Module，提供 Node 测试命令；页面不需要 npm 构建。 |

### 2.4 前端页面与组件 — `apps/management_web/static/`

| 文件 | 功能简介 |
|---|---|
| `index.html` | SPA 外壳、Logo 与“AI 监测系统”名称、导航容器、内容区和详情对话框。 |
| `styles.css` | 页面、导航、卡片、图表、知识编辑器、设置、聊天和响应式布局样式。 |
| `app.js` | 页面装配入口，负责七个页面导航、状态轮询、设备选择和各工作区挂载。 |
| `components.js` | 安全 DOM 构建、图标、卡片、表格、指标和历史趋势 SVG 等展示组件。 |
| `view-model.js` | 路由、时间/单位/状态文本、筛选和图表几何等纯展示逻辑，不复制诊断阈值。 |
| `services.js` | 同源 HTTP 客户端，封装监测、知识、设置、AI 及 SSE 请求。 |
| `assistant.js` | Assistant 工作区：输入、会话历史、Normal/Streaming、Send/Stop、Activity、阅读与全屏状态。 |
| `assistant-events.js` | 有界 POST SSE 解析器，校验序号、身份及终态，不自动重连或重放请求。 |
| `knowledge.js` | 知识列表、筛选、详情、编辑、状态变更、导出与检索测试，保护未保存草稿。 |
| `settings.js` | 偏好、预算和显式密钥测试/保存交互，管理草稿，不在浏览器持久化密钥。 |
| `tool-policy.js` | Tool 授权界面与保存后配置刷新，不能自行增加 Handler 或授予模型发布资格。 |

### 2.5 Web Python 回归与辅助程序 — `apps/management_web/tests/`

| 文件 | 功能简介 |
|---|---|
| `local_session_fixture.py` | 子进程测试服务，使用真实 Flask/上报接口与临时 SQLite，不装配 AI。 |
| `test_app.py` | 页面资源、Bootstrap、监测投影、本机访问边界与独立启动参数回归。 |
| `test_ai_boundary.py` | Web Token/句柄与业务合同分离、项目身份和启动参数转交回归。 |
| `test_assistant.py` | HTTP → Assistant → Tool → SQLite 集成，验证设备冻结、质量、来源与取消，使用 Fake Gateway。 |
| `test_multi_round.py` | Normal 多轮的 2 Calls / 2 Rounds / 3 Requests、Scope、预算、用量与来源门禁回归。 |
| `test_streaming.py` | 实际 HTTP/SSE 与 Fake SDK 的预览、工具结果、来源、终态、取消和前端解析集成。 |
| `test_knowledge.py` | Knowledge Tool 授权、执行和 Source Gate，区分知识命中、无匹配与当前事实。 |
| `test_knowledge_content.py` | 知识 CRUD/状态/导出/检索 HTTP，以及实际 Knowledge Tool 共用内容库的回归。 |
| `test_settings.py` | 临时设置、虚构凭据的持久化、并发版本、预算与密钥管理回归。 |
| `test_settings_connection_budget.py` | Fake SDK 连接测试、单次授权、保存回执、错误脱敏与预算编码，不访问真实 Provider。 |
| `test_instance.py` | 数据路径、缺库拒绝、空实例初始化、防覆盖发布、启动装配及发行包边界回归。 |
| `test_data_migration.py` | 五文件迁移的只读源冻结、备份、暂存、发布竞争、摘要和失败保留，仅使用虚构数据。 |
| `test_local_session.py` | 原启动器参数、10 秒 HTTP 上报、端口冲突与仅回收自有进程回归。 |
| `test_scenario_menu.py` | 七场景菜单映射、默认/无效/退出、原控制台包装层 dry-run 与非交互兼容回归。 |
| `test_demo_launcher.py` | 演示知识完整复制、复用不覆盖、空库/忙碌源拒绝，以及 Fake SDK 三工具试用回归。 |
| `test_windows_demo_lifecycle.py` | Windows 双终端实际进程测试：菜单等待不上报、0退出、重启保留历史/新session、持续上报、端口拒绝及进程树回收。 |

### 2.6 前端 Node 回归与夹具 — `apps/management_web/tests/`

| 文件 | 功能简介 |
|---|---|
| `dom-fixture.mjs` | 离线 DOM 元素与事件替身，供组件和页面测试使用。 |
| `assistant-fixture.mjs` | Normal Assistant 界面测试的 DOM、API 和会话夹具。 |
| `assistant-stream-fixture.mjs` | Streaming Assistant 的事件、响应与交互夹具。 |
| `chart-fixture.mjs` | 图表/监测页面测试的 DOM 与数据环境。 |
| `stream-browser-bridge.mjs` | 接收 Python 集成测试提供的配置与 SSE 帧，运行实际前端解析和展示逻辑。 |
| `assistant-events.test.mjs` | SSE UTF-8 分片、顺序、身份、大小、重复帧与错误终态验证。 |
| `assistant-stream-ui.test.mjs` | Streaming 确认、预览、最终提交、Stop、断流、历史与滚动交互回归。 |
| `assistant-transport.test.mjs` | AI HTTP/SSE 客户端、Abort 信号、显式发送及禁止自动降级回归。 |
| `assistant-ui.test.mjs` | Normal 发送、取消、历史提交、Activity、安全文本与配置更新回归。 |
| `assistant-view.test.mjs` | 全屏/阅读模式切换时保留会话、草稿、滚动、请求与停止能力。 |
| `chart-ui.test.mjs` | 实际页面图表的时间间距、断点、会话、刻度和窄屏布局回归。 |
| `knowledge-ui.test.mjs` | 知识搜索防抖/输入法、编辑草稿、版本冲突、导出及详情焦点保持回归。 |
| `monitoring-ui.test.mjs` | 监测/视觉/事件页面、轮询、设备切换、缺失数据和历史范围展示回归。 |
| `event_preview.py` | 十分钟有界的临时 SQLite 事件预览，虚构数据，不装配 AI、凭据或上报服务。 |
| `settings-ui.test.mjs` | 设置草稿、显式测试/保存、凭据不回显、预算和默认偏好交互回归。 |
| `tool-policy.test.mjs` | Tool 授权保存、配置刷新、会话保留和运行中延迟刷新回归。 |
| `view-model.test.mjs` | 路由、筛选、北京时间、数据质量、图表几何及安全展示纯函数回归。 |

### 2.7 AI 应用服务 — `apps/ai_service/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | AI 应用服务包标识，不在导入时启动 HTTP 或创建第二套工具循环。 |
| `contracts.py` | AssistantBackend 与 PreparedAssistantTurn 进程内边界，不接收 Flask/浏览器对象。 |
| `service.py` | ManagementAssistantService 统一装配业务工具、运行配置、设备/Policy 冻结与实际执行。 |
| `execution.py` | Normal 执行 Scope、试用开关、发布匹配和前端确认版本计算。 |
| `streaming.py` | Streaming 发布配置与精确 Scope 匹配，不负责 HTTP 或视频传输。 |
| `history_execution.py` | 历史水质专用候选/本地试用配置、预算约束和准入判断。 |
| `normal_selection.py` | 三工具候选及分别批准的 Normal/Streaming 统一工具试用范围解析。 |
| `content_binding.py` | 将执行范围绑定到受管理的统一知识内容来源，不继承旧来源资格。 |
| `management_policy.py` | 管理 Assistant 专属 Tool Policy，支持共享策略只读继承、generation/revision 和 CAS 保存。 |
| `settings.py` | 偏好、模型/预算能力投影、显式凭据测试与保存等设置用例协调。 |
| `settings_store.py` | 无密钥 Settings JSON 的校验、偏好/预算版本和原子 CAS 持久化。 |
| `output_budget.py` | 已批准 Qwen 范围的版本化输出 Token 预算，只在精确发布匹配后生效。 |
| `credential_test.py` | 用户显式发起的一次连接测试和短期内存保存回执，不是自动启动自检。 |

### 2.8 AI 业务工具 — `apps/ai_service/business_tools/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 业务工具包标识，不通过扫描或重导出隐式装配工具。 |
| `registry.py` | 显式绑定 Current / Knowledge / History 的 Definition、校验器和 Handler，冻结设备上下文。 |
| `current_water_quality.py` | 当前水质工具，单次 Monitoring capture 后生成有限 DTO，不自行采样或查询历史。 |
| `fishery_knowledge.py` | 项目知识工具 Definition、严格 query 参数与有限证据映射，区分 OK / NO_MATCH。 |
| `water_quality_history.py` | 历史水质工具参数及有限 DTO，查询和统计复用 Monitoring；准入仍由 Scope/Policy 决定。 |

### 2.9 AI 固定配置 — `apps/ai_service/resources/`

| 文件 | 功能简介 |
|---|---|
| `assistant_execution.json` | 管理 Normal Assistant 固定执行发布范围与身份约束，不是用户 Settings。 |
| `assistant_streaming.json` | 管理 Streaming 固定范围、预算及本地试用约束。 |
| `assistant_normal_candidate.json` | Normal 三工具选择候选的冻结配置，不因存在文件而自动开放。 |
| `assistant_unified_tools.json` | Qwen Normal/Streaming 三工具统一范围与批准的本地试用约束。 |
| `water_history_candidate.json` | 历史水质工具候选的固定 Scope、预算与数据绑定约束。 |

### 2.10 AI 业务 Runtime — `apps/ai_service/runtime/`

| 文件 | 功能简介 |
|---|---|
| `README.md` | 业务 Runtime 职责、依赖和使用说明。 |
| `__init__.py` | 业务 Runtime 包标识，无启动副作用。 |
| `assistant.py` | Assistant 请求、历史、Prompt 上下文与最终结果；检查来源、完成状态和 Commit Gate，不另建工具循环。 |
| `activity.py` | 业务工具安全摘要与 Activity 投影，复用 Backend 的通用步骤投影。 |
| `catalog.py` | 工具静态展示目录，不产生 Handler 或执行权限。 |
| `locations.py` | 通过当前用户目录与项目根身份计算私有凭据位置，不读取密钥或创建目录。 |
| `policy.py` | 固定模式策略与共享 UserToolPolicyStore，配置不能创造工具 Handler。 |
| `presets.py` | 从固定资源装配维护者控制的模型 Preset，不依据本地实验自动提升能力。 |
| `release_contracts.py` | 发布 Scope、执行 Profile 与前端确认版本的冻结合同。 |
| `sources.py` | 根据实际工具执行生成 Receipt/Ledger，校验当前观测、历史和项目知识等来源要求。 |
| `streaming_contracts.py` | Streaming Scope、发布约束与有限观测合同，不另建工具循环。 |
| `resources/presets.json` | 固定服务/模型 Preset、能力及维护者发布描述，不包含用户 API Key。 |
| `resources/tool_policies.json` | 随包提供的模式策略默认值，不等于用户数据目录内的 Policy 覆盖文件。 |
| `tests/__init__.py` | Runtime 测试包标识。 |
| `tests/test_foundation.py` | 来源收据、事实/知识区别、参数拒绝、Ledger 和冻结业务合同回归。 |
| `tests/test_integration.py` | 独立 Assistant、Fake SDK、Monitoring/Knowledge 的 Normal/Streaming 与取消/提交集成。 |

### 2.11 源码资格开发工具 — `apps/ai_service/development/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 显式开发工具包边界，普通 Web 启动不导入，不进入 Wheel。 |
| `fixtures.py` | 固定隔离知识资格语料，不读取正式用户知识库。 |
| `history_qualification.py` | 历史工具固定案例、计划与经同意的单次资格执行，复用既有 Runtime。 |
| `normal_selection_qualification.py` | Normal 三工具自主选择候选的固定案例、计划和单次执行。 |
| `streaming_qualification.py` | Streaming 候选固定案例与单次探测，不改变网页发布状态。 |
| `qualification_support.py` | 管理资格辅助：安全错误码、凭据装配、有限 Trace、报告与实验 Gateway。 |
| `qualification_adapter.py` | 单次资格运行的输出预算与有限调用摘要，不改普通 Adapter 行为。 |
| `streaming_observation.py` | SDK 级 Streaming 有限统计，不保存原始 chunks、文本或参数。 |

### 2.12 AI service 回归与指纹 — `apps/ai_service/tests/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 离线应用边界测试包标识。 |
| `capture_migration.py` | 离线采集 HTTP/计划的稳定迁移指纹，不参与产品启动。 |
| `test_business_tools.py` | 工具 Definition/DTO 指纹、显式装配、参数/授权拒绝及模块职责回归。 |
| `test_execution.py` | Normal 发布配置、默认关闭、精确 Scope、冻结与非法配置回归。 |
| `test_history_candidate.py` | 历史工具准入、HTTP Policy、CAS、设备冻结、来源和离线候选测试。 |
| `test_management_policy.py` | 管理 Policy 继承、并发锁、generation/revision、CAS 和权限失败回归。 |
| `test_normal_selection.py` | 三工具候选选择、定义指纹、精确 Scope 及授权撤销回归。 |
| `test_service.py` | 无 Flask 的 AI 应用服务边界、准备/执行、上下文冻结和 epoch 回归。 |
| `test_m1_composition.py` | M1：内部 Prompt/工具装配显式选择，默认 Web Knowledge 和输入拒绝合同保持。 |
| `test_streaming_config.py` | Streaming 本地试用配置的默认开关、精确范围及非法预算拒绝。 |
| `test_unified_tools.py` | 三工具 Normal/Streaming、授权子集、来源、预算和显式确认的 HTTP/Fake SDK 集成。 |
| `test_water_history_tool.py` | 历史工具 Schema、参数归一化、Monitoring 委托、有限结果及 Runtime/Fake SDK 回归。 |
| `fixtures/r2c1d_http_baseline.json` | 分叉迁移时的 HTTP 行为基线指纹。 |
| `fixtures/r2c1d_plan_baseline.json` | 分叉迁移时的执行计划基线指纹。 |
| `fixtures/r2c2b_business_tools.json` | 业务工具迁移前后的合同与 DTO 基线。 |
| `fixtures/r2d1c_two_tools.json` | 两工具兼容范围的固定回归指纹。 |

### 2.13 通用 AI Backend — `apps/ai_backend/`

| 文件 | 功能简介 |
|---|---|
| `README.md` | Backend 模块入口、公共边界与装配说明。 |
| `__init__.py` | 通用 Backend 包标识，导入不执行 I/O。 |
| `contracts.py` | 通用执行状态、Token 用量和时间等基础合同，不包含监测领域类型。 |
| `model_options.py` | 通用生成/推理选项、能力与状态枚举以及 URL 校验。 |
| `providers.py` | 固定 Provider 服务注册与认证描述；协议存在不等于模型能力获批。 |
| `protocol_specs.py` | 版本化请求参数编码，选择具体 Provider 协议字段，不授予资格。 |
| `model_gateway.py` | 模型 Profile、冻结 RuntimeSnapshot、消息/请求/响应/工具定义和离线 Gateway 合同。 |
| `openai_compatible_adapter.py` | 唯一 OpenAI-compatible Chat Completions SDK 传输边界，支持 Normal/Streaming 和分片组装。 |
| `sdk_resources.py` | M1：SDK 资源租约、关闭确认、并发上限及进程内清理失败隔离；不创建 QQ 入口。 |
| `execution.py` | 请求句柄、注册、ContextVar、Stop 与整轮 Deadline 生命周期。 |
| `tool_conversation.py` | 共用有界工具调用协调循环、步骤、预算及 Normal/Streaming 执行结果。 |
| `tool_argument_diagnostics.py` | 参数拒绝的有限诊断元数据，不输出原始参数、字段名或异常文本。 |
| `assistant_activity.py` | 执行步骤、用量和状态的白名单 Activity 投影，不复制工具原始结果。 |
| `assistant_events.py` | 有界、有序的 Assistant 事件通道；HTTP/SSE 发布由 Web 负责。 |
| `history_projection.py` | 产品与冻结实验共享的历史表示和保留投影，不负责历史数据库。 |
| `observability.py` | 白名单 JSONL Trace，记录有限步骤/用量/错误，不序列化 Prompt、凭据或原始事实。 |
| `credentials.py` | 凭据状态和私有快照，按请求解析 PROCESS_ENV > PROJECT_ENV > MISSING，不修改进程环境。 |
| `credential_paths.py` | 私有凭据位置、可信文件系统、所有权及权限检查，显式写入时才允许创建。 |
| `secure_files.py` | Windows/POSIX 私有文件安全操作、路径/权限检查、锁、暂存与原子替换。 |
| `project_env.py` | 固定私有 .env 的显式读写编辑，保留无关字节，异常时拒绝写入；不是源码根回退。 |
| `manual.py` | 独立专家请求/响应合同，不携带管理业务上下文或自动装配产品能力。 |

### 2.14 通用工具执行基础 — `apps/ai_backend/tools/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 通用工具类型与执行组件的包入口，业务 Handler 由上层提供。 |
| `contracts.py` | 工具 Definition、执行结果、状态和安全错误合同。 |
| `registry.py` | 显式静态工具注册，不扫描目录、动态加载或导入业务模块。 |
| `policy.py` | 单轮不可变工具授权和合法名称校验，持久化归应用层。 |
| `executor.py` | 单次请求的工具授权、参数校验与有限执行，不负责模型循环。 |

### 2.15 Backend 离线测试 — `apps/ai_backend/tests/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | Backend 测试包标识。 |
| `support.py` | 自包含 Fake SDK、脚本 Gateway、Normal/Streaming 响应与工具分片夹具。 |
| `test_assembler.py` | Streaming 工具名/参数分片组装、Unicode、终态及非法协议拒绝回归。 |
| `test_sdk_resources.py` | M1：SDK 取消/超时/清理、线程回收、资源失败禁止 Commit 与后续请求隔离。 |
| `test_boundary.py` | 无反向业务依赖、无旧包导入、独立类型和安装边界回归。 |
| `test_credentials.py` | 虚构凭据、环境优先级、私有路径/权限、原子写入和密钥脱敏回归。 |
| `test_execution.py` | 阻塞 SDK 的取消/Deadline、跨请求时间预算、资源关闭及禁止重试回归。 |
| `test_protocol_specs.py` | Provider 参数编码一致性、Token 字段、冻结快照与能力边界回归。 |

### 2.16 监测业务 — `apps/monitoring/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 共享监测包标识，不执行 Web、AI 或设备采集。 |
| `contracts.py` | 版本化上报窗口、严格 JSON/字段/单位/时间校验及观测、质量、规则、事件 DTO。 |
| `water_contracts.py` | 水质读数、质量/新鲜度类型和时间/数值校验，不依赖 AI 或 SQLite。 |
| `analysis.py` | DomainAnalysisService 共享分析入口，依据明确观测和时刻计算质量、新鲜度及规则结果。 |
| `diagnosis.py` | 水质诊断阈值、风险判断和规则版本的业务所有者。 |
| `rules.py` | 将观测、质量与诊断组织成带证据/规则身份的判断，不复制阈值或访问数据库。 |
| `events.py` | 事件 ACTIVE/RESOLVED/INDETERMINATE 纯迁移与只读投影，不是人工处理工作流。 |
| `event_families.py` | 水质同指标风险等级关联、有限变化证据与当前等级只读投影；不改变诊断阈值。 |
| `event_records.py` | 事件关注区间筛选、分页、严格删除参数和历史删除资格合同。 |
| `current.py` | 当前水质事实读取及视图，不生成模拟值、不改数据、不用 Demo 填补缺失。 |
| `history.py` | 有界历史查询合同、时间范围与区间统计，不执行当前诊断或数据库 I/O。 |
| `repository.py` | SQLite 当前值、历史、批次、事件、活动关联和联络时间；处理事务、去重、乱序及留存。 |
| `service.py` | MonitoringService 统一接入/分析/读取，绑定设备，为网页和 Tool 提供同源事实及视觉统计。 |

### 2.17 Monitoring 测试 — `apps/monitoring/tests/`

| 文件 | 功能简介 |
|---|---|
| `test_business_services.py` | 共享分析、纯事件迁移、事务回滚、重复/乱序不错误触发事件回归。 |
| `test_event_lifecycle.py` | 视觉三窗恢复、Session/缺测中断、重启、活动留存及固定 Seed 回归。 |
| `test_event_management.py` | 事件族等级、完整留存查询、五档筛选及历史删除的并发/引用保护。 |
| `test_event_wording.py` | 文案所需只读投影、旧记录兼容、原 payload 不变及三类 HTTP 读取一致性。 |
| `test_history_projection.py` | 重启、乱序、同时间观测和留存清理后的只读历史投影回归。 |
| `test_local_http.py` | 本机真实 HTTP 周期上报、重启与网页读取端到端测试，不连外部设备/模型。 |
| `test_pipeline.py` | 上报校验、窗口统计、视觉有效帧、生命周期和无数据不回退 Demo 的统一链路回归。 |
| `test_rule_governance.py` | 规则身份、单指标质量、部分覆盖、异常持续、证据缺失及可靠恢复回归。 |
| `test_water_capture.py` | 单次 capture 读取/分析一次、Web/Tool 一致、批次不可混用和结果隔离回归。 |
| `test_read_only.py` | M1：合成库只读禁止写入/迁移、并发、快照及长度/时间/工作量预算。 |
| `test_water_history.py` | 历史范围、设备隔离、时区/亚秒边界、覆盖统计和查询上限回归。 |

### 2.18 知识业务 — `apps/knowledge/`

| 文件 | 功能简介 |
|---|---|
| `README.md` | 统一知识内容模块、存储、检索及迁移入口说明。 |
| `__init__.py` | 知识包标识，正式内容来自实例 SQLite，不在导入时加载旧 JSON。 |
| `__main__.py` | 显式本地知识迁移 CLI，默认 dry-run，不访问模型或凭据。 |
| `repository.py` | 权威知识 SQLite：记录、版本、状态、来源、修订及有界事务/CAS。 |
| `service.py` | 知识 CRUD、列表/过滤、状态、导出和一致语料快照，协调检索缓存。 |
| `retrieval.py` | TF-IDF 检索和排序，消费不可变知识块，不运行 LLM 或向量数据库。 |
| `evidence.py` | 独立只读证据合同，保留证据 ID、来源、版本及检索时间。 |
| `legacy_import.py` | 一次性旧 JSON 分块转换，仅用于显式迁移/固定夹具，不是产品启动数据源。 |
| `migration.py` | 迁移计划、摘要、SQLite Backup API、校验和拒绝覆盖发布，正式读取仍由统一 SQLite 完成。 |

### 2.19 Knowledge 测试与隔离语料 — `apps/knowledge/tests/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 知识离线测试包标识。 |
| `support.py` | 为隔离测试显式建库或创建参考检索服务，不打开用户数据库。 |
| `test_content.py` | CRUD、状态恢复、版本冲突、容量、并发编辑与索引快照一致性回归。 |
| `test_unified_store.py` | 旧库迁移、完整来源/版本保留、备份、不覆盖、检索一致性及导出回归。 |
| `fixtures/README.md` | 固定知识夹具的来源和使用边界。 |
| `fixtures/eel_knowledge_v1.json` | 自包含旧版鳗鲡知识语料，仅供隔离测试与显式资格夹具，不是正式知识库。 |

### 2.20 模拟生产端 — `apps/simulator/`

| 文件 | 功能简介 |
|---|---|
| `__init__.py` | 独立确定性模拟器包标识，只经 HTTP 上报，不直接写服务端数据库。 |
| `__main__.py` | Simulator CLI、周期调度、完成窗口等待和丢过期窗口策略，支持不联网 dry-run。 |
| `generator.py` | 水质采样、模拟视觉帧、窗口聚合、种子和统一时间线，生成批次/会话/序号。 |
| `scenarios.py` | 正常、低氧、疑似病害、摄食下降、组合异常和离线等手写场景阶段。 |
| `transport.py` | 仅本机 HTTP 上报，携带接入 Token，限制超时，禁止代理/重定向及自动重试。 |
| `tests/test_simulator.py` | 种子可重现、场景、独立采样周期、统计、离线与调度时钟回归。 |

### 2.21 启动与离线测试脚本 — `scripts/dev/`

| 文件 | 功能简介 |
|---|---|
| `启动演示系统.cmd` | Windows 双击入口，启用演示实例、双终端及 Simulator 场景菜单，并打开浏览器。 |
| `run_local.ps1` | 定位本项目 .venv，传递场景/数据根/AI 开关，支持双终端、后台监护与错误提示。 |
| `local_session.py` | 复用 Web/Simulator CLI，显式场景菜单、临时接入 Token、端口/就绪检查与自有服务回收。 |
| `windows_job.py` | Windows Job Object 生命周期保护，将监护进程及后代纳入同组，退出时回收子进程。 |
| `demo_instance.py` | 首次创建独立空监测库、只读备份正式知识和建立演示授权，后续复用并拒绝空库静默覆盖。 |
| `run_management_tests.py` | 独立管理回归入口，要求隔离 Python，阻断旧 Prototype 导入并复用测试发现。 |
| `run_tests.py` | 离线 Python/Node 测试分组、发现与执行，把 TEMP/TMP 置于 outputs/test-tmp。 |

### 2.22 维护与发行准备 — `scripts/`

| 文件 | 功能简介 |
|---|---|
| `maintenance/migrate_management_data.py` | MIG-4B 五个固定业务文件的 dry-run/apply/verify，包含源冻结、备份、摘要、暂存和 Windows 防覆盖发布；非日常启动。 |
| `packaging/management.pyproject.toml` | MIG-2 staging 发行模板，当前仓库直接构建以根 pyproject.toml 为准。 |
| `packaging/prepare_management.py` | 在工作区 outputs 下建立全新白名单发行 staging，不复制数据库、测试、development 或运行数据。 |

### 2.23 显式模型资格脚本 — `scripts/qualification/`

| 文件 | 功能简介 |
|---|---|
| `qualify_management_history.py` | 历史工具固定案例单次资格 CLI，校验计划与授权后委托现有实现，默认 dry-run。 |
| `qualify_management_history_batch.py` | 固定 3 类案例各 5 次的计划、子进程调用及报告汇总，不增加重试或另一套工具循环。 |
| `qualify_management_normal_selection.py` | Normal 三工具选择候选单案例资格入口，默认 dry-run，不改变产品发布状态。 |
| `qualify_management_streaming.py` | Streaming 候选单案例资格入口，默认 dry-run，不自动批量调用。 |

### 2.24 用户主动测试入口 — `scripts/manual_real_tests/`

| 文件 | 功能简介 |
|---|---|
| `README.md` | 人工作业的同意范围、dry-run 及真实连接/资格测试方式说明。 |
| `run_qualification.py` | 人工作业统一委托入口，默认只生成计划，不新建模型循环或自动调用 Provider。 |

### 2.25 当前操作与接口文档 — `apps/docs/`

| 文件 | 功能简介 |
|---|---|
| `README.md` | 当前文档导航与阅读顺序。 |
| `BUILD_RUN.md` | 安装、双击演示、正式 Web-only、隔离联调、数据路径、离线测试和发行命令。 |
| `USER_GUIDE.md` | 页面操作、启动/关闭、业务数据/凭据边界、备份和日常使用学习指南。 |
| `STRUCTURE.md` | 本页，包含简略分层图与逐文件职责索引。 |
| `INTEGRATION.md` | 统一监测协议、HTTP DTO、规则/事件、AI 与前端集成合同及边界。 |
| `deep-dive/EVENT_LIFECYCLE.md` | 视觉三窗恢复、Session/缺测、持久化、活动留存和首页异常概况。 |
| `deep-dive/EVENT_MANAGEMENT.md` | 水质事件族等级、准确状态文案、关注区间筛选和受控历史硬删除。 |
| `ROADMAP.md` | 已完成阶段、当前能力与待选择方向，不把规划当作已实现功能。 |

### 2.26 开发、资格与迁移说明 — `apps/docs/deep-dive/`

| 文件 | 功能简介 |
|---|---|
| `AI_BACKEND_DEVELOPMENT_GUIDE.md` | Backend/Assistant 分层、Tool、Prompt、Scope、预算、来源及安全合同开发指南。 |
| `KNOWLEDGE_CONTENT.md` | 统一知识内容 Schema、CRUD、检索、来源、版本和显式迁移设计。 |
| `HISTORY_QUALIFICATION.md` | Qwen 历史工具的固定案例、预算、资格流程与本地试用边界。 |
| `STREAMING_QUALIFICATION.md` | Streaming 候选资格、观测、预算与本地试用说明。 |
| `MANAGEMENT_STANDALONE.md` | MIG-2 独立发行、实例路径、初始化及已有实例保护设计。 |
| `MIG3_STANDALONE.md` | MIG-3 新项目独立化、项目身份与迁移边界记录。 |
| `MIG4_DATA_MIGRATION.md` | MIG-4B 正式业务数据迁移、安全检查、执行回执及恢复边界。 |
| `R2D2A_PRODUCT_INTEGRATION.md` | Policy 锁等产品整理与候选准入的阶段性实现/验证记录。 |
| `R2D2B_UNIFIED_TOOLS.md` | 固定 Send/Stop 操作栏与 Qwen 三工具 Normal/Streaming 本地试用实现记录。 |

### 2.27 历史研究与方案 — `apps/docs/deep-dive/research/`

| 文件 | 功能简介 |
|---|---|
| `R2B_DOMAIN_ANALYSIS_AND_AI_INTEGRATION.md` | 领域分析与 AI 集成的早期架构审阅、事实边界和分层建议。 |
| `R2B3_MANAGEMENT_AI_ARCHITECTURE_REVIEW.md` | 管理 AI 参数拒绝、证据边界及架构职责审阅。 |
| `R2B5_MANAGEMENT_ASSISTANT_STREAMING_INTEGRATION.md` | 管理 Assistant Streaming 集成前的现状、差距与方案。 |
| `R2C1A_LLM_BACKEND_AUDIT.md` | 原 LLM Backend 依赖审计、模块分类和迁移判断。 |
| `R2C1B_AI_BACKEND_FORK_MIGRATION_PLAN.md` | 管理 Backend 选择性分叉、公共类型所有权及回归迁移计划。 |
| `R2D1A_WATER_HISTORY_TOOL_DESIGN.md` | 历史水质工具加入前的合同、查询范围、统计和资格设计。 |
| `R2D1_TOOL_RETROSPECTIVE_AUDIT.md` | 历史 Tool 工程复盘、架构成本与流程审计。 |
| `R2D1F_TOOL_INTEGRATION_COST_AUDIT.md` | 历史 Tool 集成成本统计、复杂度来源和改进方向。 |

### 2.28 独立化前文档快照 — `apps/docs/history/`

| 文件 | 功能简介 |
|---|---|
| `README_PRE_MIG3.md` | MIG-3 前文档导航快照，仅供历史对照。 |
| `BUILD_RUN_PRE_MIG3.md` | MIG-3 前安装/启动说明，不代替当前 BUILD_RUN.md。 |
| `ROADMAP_PRE_MIG3.md` | MIG-3 前能力和路线图快照，不代表当前待办状态。 |
| `STRUCTURE_PRE_MIG3.md` | MIG-3 前目录地图，可能引用旧工作区，不是当前依赖清单。 |

## 三、不逐文件展开的环境与业务数据

下面是路径规则示意，**不表示每个目录或文件当前必然存在**。真实内容、凭据和运行产物不属于上面的源码清单。

| 位置 | 用途与注意事项 |
|---|---|
| `.git/` | 本项目独立 Git 元数据，不与其他仓库混用，也不手工修改内部文件。 |
| `.venv/` | 本项目 Python 环境和依赖，不使用旧项目虚拟环境。 |
| `outputs/demo-instance/` | 双击演示专属实例：独立 Monitoring、首次复制的知识、演示授权及后续保存的演示设置。 |
| `outputs/dev-instance/` | 文档示例的独立开发实例，显式创建后才存在。 |
| `outputs/test-tmp/` | 自动测试 TEMP/TMP、虚构数据库和临时材料，不使用正式实例。 |
| `outputs/` 内其他运行产物 | 资格报告、构建 staging、发行产物等，实际子目录由对应脚本决定。 |
| `%LOCALAPPDATA%\FisheryManagement\` | `--user-data` 选择的正式业务根，包括两库、Settings、Policy 和按需生成的 Trace。 |
| 显式 `--data-root` 指定目录 | 同一结构的独立业务实例，路径统一由 ManagementPaths 解析。 |
| `apps/knowledge_data/`、`outputs/management_web/`、`outputs/tool-policies/` | 不显式选择数据根时保留的仓库相对兼容路径，不会自动指向正式用户数据。 |
| 项目独立私有 Credential Store | Windows 为 `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<项目根身份摘要>\credentials\.env`。历史父目录名不构成旧项目依赖，也不在演示业务根内；不复制、输出或提交密钥。 |

显式业务实例的路径布局：

```text
<data-root>/
├── monitoring.sqlite3                         # 当前值、历史、批次和事件
├── knowledge.sqlite3                          # 权威知识、状态、版本和来源
├── settings.json                              # 按需保存，无密钥偏好/预算
├── tool-policies/
│   ├── management_assistant_policy.json        # 管理授权覆盖，按需创建
│   └── tool_policies.json                     # 可选共享兼容授权
└── logs/
    └── assistant-traces.jsonl                  # 按需写入，有限执行 Trace
```

已有实例缺库、损坏或不兼容，应核对来源与备份，不能通过空白初始化掩盖。演示首次只复制正式知识，不复制正式 Monitoring、Settings、Policy、Credential 或 Trace；后续不覆盖演示编辑。真实数据、密钥、迁移备份和运行报告不应加入 Git。

## 四、按任务快速定位

以下简写路径以 `apps/` 为起点；启动脚本以项目根为起点。

| 想了解或调整什么 | 先看哪里 |
|---|---|
| 双击演示、两个窗口启停 | `scripts/dev/启动演示系统.cmd` → `run_local.ps1` → `local_session.py`；初始化看同目录 `demo_instance.py`。 |
| 当前业务数据从哪读 | `management_paths.py`、`management_web/__main__.py` 和 `management_web/instance.py`。 |
| 真实设备接入前核对合同 | `monitoring/contracts.py`、`monitoring/service.py` 和 Web 上报路由；现合同仍为本机模拟来源。 |
| 修改水质规则 | `monitoring/diagnosis.py` 管阈值，`analysis.py` / `rules.py` 管质量、证据与规则投影。 |
| 修改历史统计或事件 | `monitoring/history.py` / `events.py`，持久化事务在同目录 `repository.py`。 |
| 修改页面或交互 | `management_web/static/`，对应 Node 用例在 `management_web/tests/`。 |
| 增加 AI 业务 Tool | `ai_service/business_tools/` 显式注册，核对 Policy、Scope、Source Ledger 和回归，不复制 Backend 循环。 |
| 修改模型协议/传输 | `ai_backend/protocol_specs.py` / `openai_compatible_adapter.py`；资格和业务范围仍由 AI service 决定。 |
| 排查知识编辑或检索 | `management_web/knowledge_api.py` → `knowledge/service.py` → `repository.py` / `retrieval.py`。 |
| 查当前操作或历史决策 | 当前看 BUILD_RUN / USER_GUIDE / INTEGRATION；历史看 research / history，不直接套用旧路径。 |

新增、删除或迁移源码文件时应同步详细版。当前用户操作见 [使用指南](USER_GUIDE.md)，工程命令见 [BUILD_RUN](BUILD_RUN.md)，Tool、Prompt、Scope 和安全合同见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。

## EVT 收尾新增模块

| 文件 | 功能 |
|---|---|
| `monitoring/event_cycles.py` | 全留存数据按稳定风险周期汇总后筛选、分页。 |
| `monitoring/event_handling.py` | 周期及等级版本 ACK、幂等请求、人工状态投影。 |
| `monitoring/event_cycle_deletion.py` | 可靠已结束周期与全部 ACK 的显式事务删除、成员及外部引用检查。 |
| `monitoring/schema.py` | v2 表、RESTRICT 外键及实例兼容校验。 |
| `monitoring/migrate.py` | 手工显式 v1→v2 维护，防覆盖备份和逻辑摘要检查；普通启动不调用。 |
| `monitoring/tests/test_event_ack.py` | ACK 等级、重启、权限、并发及保留保护。 |
| `monitoring/tests/test_ack_cycle_deletion.py` | 周期删除、回滚、引用、其他周期及观测保全。 |
| `monitoring/tests/test_event_cycles.py` | 周期汇总、全库筛选分页与原接口兼容。 |
| `monitoring/tests/test_event_legacy.py` | 旧事件状态投影与受控清理兼容。 |
| `monitoring/tests/test_monitoring_migration.py` | 隔离 v1 升级、备份、拒绝覆盖与故障回滚。 |
| `docs/deep-dive/EVT_SYNC_ACCEPTANCE.md` | 本轮同步范围、真实库只读核查及待审批升级。 |

## 失联提醒人工结束

| 文件 | 功能 |
|---|---|
| `monitoring/manual_end.py` | 周期/旧单条人工结束，JSON人工序号、证据、幂等、事务复查及重新提醒。 |
| `monitoring/tests/test_manual_end.py` | 合成失联、新HIT、旧记录、Session、并发、校时、删除和留存保护。 |
| `management_web/tests/event_preview.py --manual-end` | 临时虚构失联记录的限时预览，不读取真实实例或Provider。 |
| `docs/deep-dive/EVENT_MANUAL_END.md` | 功能边界、API、记录保留与无真实数据的人工预览。 |
| `docs/deep-dive/MANUAL_END_SYNC.md` | 本次复核、选择性同步与独立回归记录。 |
