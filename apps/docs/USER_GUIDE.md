# Fishery Management 使用与学习指南

核对日期：2026-10-19。当前发行版本为 `0.1.0`，代码位于 `D:\CodexProject\Fishery_Management`。

MIG-1～MIG-5 的主要独立化、业务数据与凭据准备已完成，用户已确认基本网页验收。本指南依据当前源码和脚本整理；本轮没有读取真实数据库或密钥，没有重新执行模型、硬件或网页验收。迁移完成不等于获得生产环境发布资格。

## 1. 项目是什么

Fishery Management 是一个本机智慧渔业管理应用，把监测事实、规则结果、事件、知识内容和 AI 辅助对话集中到同一网页中。目前使用 Python / Flask、SQLite 和原生 JavaScript，无需前端构建。它已独立于原 AI Prototype 运行。

| 页面 | 现在可以做什么 | 当前边界 |
|---|---|---|
| 首页 / 综合总览 | 查看水质概况、历史趋势、近期事件、连接状态，进入 AI 助手 | 监测来源仍是模拟器，不是真实养殖场在线数据 |
| 水质监测 | 选择设备、查看温度 / pH / DO、窗口样本、时间、质量及历史曲线 | 实验规则标为 `PROTOTYPE`；缺失或过期数据不能作为当前正常证据 |
| AI 智能助手 | Qwen Normal / Streaming、本轮自主选择只读 Tool、多轮、Stop、来源与用量 | `local_experimental` 本地实验；回答仍需人工判断 |
| 视频监控 | 查看模拟视觉窗口、疑似异常、行为占比、可见鱼数与体长统计 | 没有真实视频流、NPU 推理、录像或截图；疑似信号不是确诊 |
| 事件记录 | 按关键词、等级、状态筛选，查看设备、批次、规则和来源详情 | 没有生产级告警通知、人工处理闭环或关联媒体存储 |
| 资料与知识库 | 添加、查看、编辑、停用、软删除、恢复、搜索、导出和检索测试 | 文本知识；没有 PDF 解析、Embedding 或向量检索 |
| 系统设置 | 保存默认偏好、测试与保存密钥、调整预算、管理 Tool 授权 | 本机访问保护，不是远程多用户权限系统 |

**“正式数据实例”表示用户实际保存的数据位置；其中的监测记录仍可能全部来自模拟器。** 数据位置、来源真实性、规则成熟度和模型发布资格是不同概念。

## 2. 启动与关闭

### 2.1 先进入新项目

使用普通 PowerShell，保留终端窗口供观察和停止服务：

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_Management'
```

使用本项目自己的 `.venv`。安装方法见 [BUILD_RUN](BUILD_RUN.md)，不要复用旧 Prototype 的虚拟环境或 `PYTHONPATH`。

### 2.2 日常使用正式用户数据：只启动 Web

已完成数据迁移的本机，推荐使用以下一行命令：

```powershell
.\.venv\Scripts\python.exe -I -B -m apps.management_web --project-root "$PWD" --user-data --enable-assistant --assistant-multi-round-trial --assistant-streaming-trial --assistant-history-trial --assistant-tools-trial
```

- 访问 [http://127.0.0.1:8766](http://127.0.0.1:8766)。仅监听本机。
- 使用 `%LOCALAPPDATA%\FisheryManagement` 已有实例；**不启动 Simulator，不开放数据上报接口**。页面编辑知识、保存设置及用户发起 AI 请求仍有各自的写入行为。
- 启用已经批准的 Qwen OFF 三工具 Normal / Streaming 本地实验。工具还须在系统设置中获得用户授权，密钥也须可用；启动参数不会替用户改 Policy。
- 未设置偏好时响应模式为 Normal；保存过的默认偏好可以恢复为 Streaming。打开页面、切换模式和刷新状态都不会自动调用模型。
- 启动本身不请求模型；点击“发送”或“测试连接”才可能产生真实请求及费用。

已有实例缺库、损坏或版本不兼容时会拒绝启动。请核对路径和备份，**不要对正式目录使用 `--init-data` 来“修复”问题**。

### 2.3 开发联调：隔离实例 + Simulator

这类实例用于生成可丢弃的模拟数据，与正式用户数据分开。首次创建时，目标目录必须不存在，父目录必须存在：

```powershell
New-Item -ItemType Directory -Path '.\outputs' -Force | Out-Null
.\.venv\Scripts\python.exe -I -B -m apps.management_web --project-root "$PWD" --data-root "$PWD\outputs\dev-instance" --init-data
```

初始化创建空 Monitoring / Knowledge 数据库及必要目录，不复制用户知识、设置、授权或密钥。已有实例不要重复初始化；空知识库需要在网页中录入内容后，Knowledge Tool 才有可检索资料。

后续每次一行启动 Web 和 Simulator：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\dev-instance"
```

此命令每 10 秒向**所选隔离实例**上报水质和视觉窗口，默认启用已批准的 Assistant 与 Qwen 本地实验。**隔离数据根不隔离凭据**：同一项目启用 AI 仍使用该项目的私有 Key，主动发送可能计费；它不会自动变成 Fake Provider。若只观察模拟数据、希望完全不装配 AI 和私有凭据，使用：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\dev-instance" -NoAssistant
```

场景可选 `normal`、`low_oxygen`、`suspected_disease`、`reduced_feeding`、`combined_anomaly`、`device_offline`；`-Seed 42` 为默认随机种子。停止后更换 `-Scenario` 再启动即可开始新的模拟会话；不要据此把跨会话历史解释为连续观测。

**注意：`run_local.ps1` 始终启动 Simulator，没有“只启动 Web”参数。** 加 `-NoAssistant` 也仍然写监测数据。不要把 `-DataRoot` 换成 `-UserData` 作为日常默认操作：这样会向正式监测库写入模拟数据，并按有界留存策略淘汰较早历史。确需进行这种写入时应先备份并明确选择。

需要单独观察 Simulator 生成过程而不发送 HTTP，可以使用以下有限预览；它不会启动模型或 NPU：

```powershell
.\.venv\Scripts\python.exe -I -B -m apps.simulator --scenario low_oxygen --interval 10 --windows 3 --dry-run
```

### 2.4 停止、端口与关闭实验

- 在启动终端按 **Ctrl+C**。Web 单独启动时停止 Web；一键启动器会回收自己创建的 Web 和 Simulator 子进程。关闭浏览器标签页不等于停止服务器。
- 尽量使用 Ctrl+C 后等待终端返回，不要依赖强制关闭窗口或重启电脑进行清理。
- 默认端口为 `8766`。端口被占用时不要再启动第二份，也不要自动结束未知进程。先找到原启动终端停止，或在 Web 命令末尾加 `--port 8767`；一键启动器使用 `-Port 8767`，访问地址同步改变。
- 一键启动器遇到端口冲突会拒绝启动，不会杀掉未知进程。
- 只关闭 Streaming：停止服务，在 Web 启动命令中移除 `--assistant-streaming-trial` 后重启；开发启动器加 `-NoStreaming`。原有数据和授权不删除。
- 完全关闭 AI，仍查看正式数据：

```powershell
.\.venv\Scripts\python.exe -I -B -m apps.management_web --project-root "$PWD" --user-data
```

该命令同样不启动 Simulator。原始服务器 CLI 默认关闭 AI 与全部实验开关；启用开关只授予精确本地实验范围，不能突破工具授权或变成生产 `released`。

## 3. 页面怎么用

### 3.1 总览、水质与历史

1. 在“水质监测”选择观测区域，确认设备、来源、窗口和观测时间。
2. 在历史图选择温度、pH 或 DO，以及“最近 30 分钟”“最近 1 小时”“全部存储历史”。“全部”仅指当前服务保留并返回的历史，不是无限归档。
3. 展开样本详情和已存储历史表，核对有效样本、无效样本与具体时间。曲线中的缺口、跨会话或重叠不能解释为持续正常。

水质主要展示 **10 秒窗口内有效采样的算术平均值**，不是瞬时传感器读数。页面每 5 秒读取服务器；读取和刷新不会重新采样。时间统一显示到秒，标为北京时间（`Asia/Shanghai`）；内部时间使用带时区时间戳。

默认超过观测时间 30 秒标为过期；通道距服务器记录的最近一次上报联系超过 90 秒标为离线。二者依据不同时间，不能互相替代；有联系也不证明测量质量有效。停止模拟器后出现过期 / 离线是预期行为，不代表数据库丢失。`NO_DATA`、部分缺失、无效和过期值均不能当作当前正常状态。

### 3.2 AI 智能助手

1. 先在“系统设置 → Assistant Tool 授权”启用需要的工具并保存。
2. 进入 AI 页面，选择 **Qwen 3.8 Flash**、监测设备与 Normal / Streaming；确认页面显示可用。
3. 输入问题，点击“发送”或按 **Ctrl+Enter**。主动发送即授权本次冻结配置的模型请求，无需逐条勾选联网框。
4. 查看独立 Tool 卡片、来源和运行面板。Normal 完成后显示回答；Streaming 先显示临时预览，再在同一位置成为正式回答。

| 工具 | 适合的问题 | 来源含义 |
|---|---|---|
| 当前水质 | “当前 DO 是多少？数据是否新鲜？” | 统一 Monitoring 中本设备当前事实及规则结果 |
| 历史水质 | “过去 30 分钟 DO 有什么变化？” | 最近 10 / 30 / 60 分钟的有界窗口统计、覆盖与缺口；不是当前观测 |
| 项目知识 | “项目资料中如何解释低氧风险？” | 当前启用知识内容；不能证明现场事实或疾病确诊 |

模型自主选择已授权且实际可用的工具。Qwen 三工具本地实验每个 Turn 最多 **2 次 Tool / 2 轮 / 3 次模型请求**，每轮最多一个 Tool，retry=0，整 Turn 期限 120 秒。三种工具可选，不表示可以一次执行三次；同时需要三类来源时应分次提问，不能编造缺少的来源。

- **Stop** 取消本轮，失败、超时、截断或断线会撤销临时预览，不将其加入成功 History；远端计算或计费是否停止不保证。
- 不自动重试、不自动改用 Normal 或其他模型。需要重发时，由用户检查后主动操作。
- 切换 Normal / Streaming 保留本会话成功 History，只影响下一条消息。执行期间模式与设备冻结；切换模型或设备会提示开始新会话。
- 聊天不是持久化档案；刷新页面或后端重启后不能指望恢复原对话。重要内容可及时使用阅读模式查看或截图。
- 右上角“进入全屏”扩大工作区；“阅读 / 截图”展开正文便于整页截图；ESC 退出，运行面板可折叠。侧边问题标记可跳转；主动向上阅读时暂停自动跟随。
- 提示配置已变化时，点击右上角“刷新可用状态”，核对授权、设备与模式后再主动发送；刷新本身不发送问题，也不清除同一后端会话的成功 History。

Ollama 预设仍在列表中，需本机服务和相应模型；其具体可用模式以页面为准，不继承 Qwen 三工具资格。DeepSeek Backend 适配与密钥连接测试保留，但不是当前管理聊天的可选主力模型。不要因“连接测试成功”认为它自动获得工具或 Streaming 发布许可。

### 3.3 资料与知识库

- 搜索关键词自动防抖查询，也可按 Enter；分类和状态筛选继续生效。
- 点击标题或“查看”打开详情；底部“确定”关闭详情并返回列表。编辑后点击“保存知识”；有未保存更改时按页面提示处理。
- 内置导入知识与用户知识都在管理数据库中编辑，保留原始来源，不改写旧 Prototype 的 JSON。
- “停用”或“删除（可恢复）”后不再进入有效检索；通过状态筛选找到记录并恢复启用。
- 保存后下一次检索使用新版本，无需重启服务；正在进行的检索使用自己的内容快照。
- 右上角“导出知识库”可选 JSON / Markdown、当前启用 / 全部。下载不修改数据库，不是自动同步源。
- 底部“高级功能 · 检索测试”默认折叠，展开后可测试实际 TF-IDF 命中及来源；**不调用 LLM**。

当前正文最多 6000 字、标题 120 字、分类 40 字；最多 200 条（含可恢复删除）。知识只是供检索的不可信背景内容，不能作为系统指令；LLM 没有知识写入 Tool。

### 3.4 系统设置

| 区域 | 操作与生效方式 |
|---|---|
| 常规设置 | 保存默认模型、设备、响应模式和默认展开详情；下次打开页面恢复，不更改进行中的对话 |
| AI 模型管理 | 查看固定预设、连接方式和模式可用性，选择默认模型；暂不支持添加模型或修改 Provider 地址 |
| API 密钥 | 输入新 Key → 点击“测试新密钥（1次请求）”→ 成功后保存 / 替换。更换输入、并发修改或超过 5 分钟须重新测试；清除需要明确确认 |
| 回答与执行预算 | Normal / Streaming 分别保存或恢复默认；只有匹配已批准 Qwen 本地范围时可编辑 |
| Assistant Tool 授权 | 当前、历史、知识独立启停；只影响后续 Turn，不改正在执行的权限快照 |
| RAG 检索设置 | 查看当前 TF-IDF 与固定限额；高级参数没有编辑入口 |

**密钥测试是真实连接，可能计费**：最多一次模型请求、8 输出 tokens、20 秒，不保存输入密钥，不证明回答质量、Tool 或 Streaming 资格。测试失败原 Key 不变；可单独测试已保存 Key。进程环境 `PROCESS_ENV` 优先且只读，网页不能覆盖它。

Qwen 受控本地多轮范围允许每请求 **1～4096 的整数**；推荐 512 / 1024 / 2048 / 4096。原统一范围默认 Normal **1024**、Streaming **512**，已保存覆盖值以页面“当前 Tokens / 请求”为准。超界不静默截断，其他模型 / 未开放模式没有相同编辑许可。

输出 tokens 只控制一次模型生成长度，不是 Tool 次数或整轮总量。增大它不改变 2/2/3、retry=0 或 120 秒期限，也不能保证模型不截断。保存后的预算、权限和凭据更新只影响新请求；已经开始的 Turn 继续使用原快照。

### 3.5 视频与事件

视频页目前只展示模拟窗口汇总，没有播放真实视频。可见鱼数是有效画面平均值，不是鱼池存量；体长是有效检测记录加权统计，不代表鱼群真实平均体长。未标定或无有效测量时不应出现可信厘米值。

事件可筛选、查看详情，但不能当作完整告警管理系统。`ACTIVE` 表示异常持续，`RESOLVED` 表示有可靠新证据确认消退，`INDETERMINATE` 表示当前证据不足。没有数据或离线不等于恢复；疾病相关条目只是疑似检测信号，规则仍为 `PROTOTYPE`。

## 4. 数据、凭据与备份

### 4.1 三种位置要分开

| 内容 | 位置与用途 |
|---|---|
| 程序与文档 | `D:\CodexProject\Fishery_Management`，由 Git 管理 |
| 正式用户实例 | 显式使用 `--user-data` 时为 `%LOCALAPPDATA%\FisheryManagement` |
| 开发实例 | `--data-root` / `-DataRoot` 指定的绝对路径，例如本项目 `outputs\dev-instance` |
| 私有 Credential | `%LOCALAPPDATA%\Fishery_AI_Prototype\project-<项目身份摘要>\credentials\.env`，不属于业务数据根 |

Credential 目录保留历史产品名，但项目身份按**当前项目根路径**生成，不代表仍依赖旧运行代码。移动 / 改名项目目录可能选择另一个凭据身份；不要手动复制 `.env` 或以源码根 `.env` 代替，先确认身份，再通过设置或受控迁移处理。优先级为 `PROCESS_ENV > 用户私有 PROJECT_ENV > MISSING`。

选定数据根的结构：

```text
FisheryManagement/                 # 或明确指定的开发实例根
├── monitoring.sqlite3            # 当前状态、窗口历史与事件
├── knowledge.sqlite3             # 唯一权威文本知识库
├── settings.json                 # 默认偏好与输出预算，按保存操作创建
├── tool-policies/
│   ├── management_assistant_policy.json
│   └── tool_policies.json        # 共享 Policy 兼容读取；不是第二套网页授权
└── logs/assistant-traces.jsonl    # 安全执行 Trace，按使用生成
```

**技术默认值与推荐操作不同**：代码为兼容旧合同，省略所有数据根参数时仍指向本项目 `outputs/management_web/`、`outputs/tool-policies/` 和 `apps/knowledge_data/knowledge.sqlite3`。日常不要省略参数；显式实例不会悄悄回退读取这些路径或旧仓库。`apps/knowledge_data` 不是使用 `--user-data` 时的正式存储位置。

### 4.2 什么要保留

- 不随意清理正式实例、私有凭据、迁移备份、无法确认用途的 SQLite 边车文件（`-wal`、`-shm` 等）。
- `outputs/` 用于测试、构建和运行报告，但其中也可能包含手动建立的开发知识或监测实例；先判断内容是否仍有价值，再清理。
- 数据库、设置、Policy、Credentials、Trace 与导出文件可能包含业务或私人信息。它们不是代码，不应提交到 Git；忽略规则不能代替人工检查暂存内容。
- 系统不会自动在新旧项目之间同步知识、监测库或密钥；不要让两个系统写同一套正式文件。

### 4.3 迁移备份不等于日常备份

MIG-4 备份是迁移时的一次性基线，位于 `%LOCALAPPDATA%\FisheryManagement.mig4b-backup-<操作ID>`，含校验回执。它不会包含后续编辑；不要因迁移完成就删除，也不要把迁移脚本反复作为备份工具。

知识页面 JSON / Markdown 导出适合阅读、交换与额外留档，但不包含完整数据库元数据、监测历史、设置或 Policy；当前没有通用的一键导出恢复功能。

已有的**知识 SQLite 专用备份**使用 SQLite Backup API、检查完整性、拒绝覆盖目标。确认数据库位置，选一个新的备份文件；以下操作由用户需要时主动执行，本次文档任务没有执行：

```powershell
.\.venv\Scripts\python.exe -I -B -m apps.knowledge --target "$env:LOCALAPPDATA\FisheryManagement\knowledge.sqlite3" --backup-to "$env:LOCALAPPDATA\FisheryManagement\backups\knowledge-$(Get-Date -Format yyyyMMdd-HHmmss).sqlite3" --apply
```

这只备份知识库。完整日常备份应暂停 Web、Simulator 及其他写入器，对两个 SQLite 使用安全备份方法并校验，连同 Settings / Policy 留存；不要在写入期间只复制主 SQLite 文件。凭据另行私密保护，不放入普通备份或 Git。当前没有自动备份调度或完整实例自动恢复；恢复前需单独确认目标、现有新数据和回退点，不能直接覆盖。

## 5. 程序目录与各层职责

```text
Fishery_Management/
├── README.md / AGENTS.md / pyproject.toml / .gitignore
├── apps/
│   ├── management_paths.py        # 集中选择业务数据路径
│   ├── management_web/            # 网页、HTTP/SSE、本机访问检查
│   │   ├── static/               # HTML/CSS/JS 页面
│   │   └── tests/                # 管理 HTTP 与 Node 前端测试
│   ├── ai_service/                # 设备/权限/预算装配、业务 Assistant
│   │   ├── business_tools/        # 三个只读业务 Tool
│   │   ├── runtime/               # 业务 Prompt、来源与提交合同
│   │   └── resources/             # 固定模型与本地发布配置
│   ├── ai_backend/                # 通用模型调用、流组装、Tool 循环、取消
│   ├── monitoring/                # 观测、质量、规则、事件、历史与 SQLite
│   ├── knowledge/                 # 文本内容管理和 TF-IDF 检索
│   ├── simulator/                 # 场景生成，经 HTTP 上报
│   └── docs/                      # 本指南、工程说明与阶段记录
├── scripts/
│   ├── dev/                       # 本地联调与离线测试入口
│   ├── maintenance/               # 受控迁移维护，不是日常启动
│   ├── manual_real_tests/         # 用户手动真实测试，默认 dry-run
│   ├── qualification/             # 既有管理资格入口
│   └── packaging/                 # 独立发行准备与检查
├── .venv/                         # 本项目环境，Git 忽略
└── outputs/                       # 隔离实例、缓存、报告与构建，Git 忽略
```

各业务包也有自己的 `tests/`，不是集中在根目录的另一个旧测试库。简化调用关系为：网页 → `ai_service` → `ai_backend`；业务 Tool → Monitoring / Knowledge → 各自 SQLite。Simulator 走受控 HTTP，不直接改网页变量。Backend 处理通用执行，业务层负责“哪些工具能用、事实来自哪里、回答是否能提交”。详见 [结构](STRUCTURE.md) 与 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。

## 6. 常用开发命令与定位问题

所有命令在本项目根执行；下面只作为操作参考，本轮文档整理未重新运行测试。

```powershell
# 快速离线检查
.\.venv\Scripts\python.exe -I -B scripts/dev/run_tests.py fast
# 完整管理离线集：Python + Node，禁止导入旧 fishery_ai
.\.venv\Scripts\python.exe -I -B scripts/dev/run_management_tests.py
# 查看依赖一致性
.\.venv\Scripts\python.exe -m pip check
# 查看工作树与近期提交；不会更改版本
git status --short --branch
git log -5 --oneline
git diff --stat
git diff --check
```

测试使用 Fake SDK / 隔离数据，不应发起真实模型请求；完整管理集需要 Node。真实 Provider / NPU 测试由用户主动运行 [手动真实测试入口](../../scripts/manual_real_tests/README.md)，人工回答质量检查另行记录，不能与技术测试或产品发布混同。

| 现象 | 先检查什么 |
|---|---|
| 端口被占用 | 原服务终端；停止已知实例或选其他端口，不杀未知进程 |
| `LOCAL_SERVER_START_FAILED` | 一键启动器隐藏子进程输出；先停止它，再用本指南 Web CLI 指向同一开发根单独启动，查看安全错误码；不加 ingestion 也能检查数据库与 AI 装配 |
| `*_DATABASE_MISSING / CORRUPT / SCHEMA_INCOMPATIBLE` | 数据根、迁移回执、备份；不要重新初始化正式实例或删除文件 |
| 旧历史显示过期 / 离线 | 来源、观测时间、最近接收时间；没有持续上报时是正常现象 |
| AI 不能发送 / 配置已变化 | AI 开关、模型/模式、工具授权、密钥状态；刷新可用状态后人工重发 |
| 回答被截断 / 超时 | 运行面板错误码与实际预算；在设置允许范围内调整后，仅主动发起新请求 |
| 参数、来源或提交拒绝 | 展开 Tool / 本次运行详情，记录安全错误码、请求标识、模式和步骤；不要复制原始参数、密钥或私有正文 |
| 保存冲突 | 其他窗口是否已修改；保留未保存输入，按页面提示重新读取后操作 |

正式实例的安全 Trace 位于数据根 `logs/assistant-traces.jsonl`，不是完整对话存档；普通 Web 启动错误在终端。现有一键启动器不另外保存子进程控制台日志，不能把它的安全 Trace 当作服务器日志。不要把完整 Trace 或业务内容直接贴到公开问题中。

## 7. 当前阶段、限制与后续记录

**当前阶段**：独立管理应用、数据和凭据准备完成，进入业务完善阶段。版本号来自 `pyproject.toml`；本次编写核对的 Git HEAD 为 `9666ae7`。迁移历史见 [MIG-3](deep-dive/MIG3_STANDALONE.md) 和 [MIG-4](deep-dive/MIG4_DATA_MIGRATION.md)；MIG-5 凭据与真实网页验收完成状态由用户确认，不在本轮冒充新资格记录。

已实现：统一 Monitoring、连续模拟器、历史基础统计、三种只读 Tool、知识内容管理、设置、密钥先测后存、受控预算、Normal / Streaming、本机访问检查。

已知限制：没有真实传感器 / NPU / 视频；规则与 AI 属于原型或本地实验；历史只提供有界基础统计，不承诺持续低氧、恢复或预测分析；历史和事件有留存上限；聊天不持久化；没有生产认证、多用户权限、远程部署与自动备份；自定义模型、高级 RAG 和模型 / 参数扩围尚未开放。

后续候选工作按需求选择：真实设备接入、领域历史分析、告警闭环、备份恢复与权限部署。它们是计划，不是本指南宣布已经完成的能力，详见 [路线图](ROADMAP.md)。

可在个人笔记中复用这个简短模板，不必新增一套文档系统：

```text
日期 / Git 分支与短提交号：
目标与涉及模块：
数据实例：正式 / 隔离（不记录密钥）
实际启动命令与场景：
验证：离线测试 / 用户真实操作 / 回答质量观察
结果与安全错误码：
已知限制、下一步、回退点：
```

更新功能时同步维护本指南的操作入口；接口与安全合同继续以 [INTEGRATION](INTEGRATION.md)、开发指南和源码为依据，避免把阶段报告中的“当时待完成”当作当前状态。
