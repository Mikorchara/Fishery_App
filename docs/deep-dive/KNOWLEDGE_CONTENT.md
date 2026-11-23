# 统一文本知识库与内容管理（R2D-3B）

## 当前实现

```text
一次性迁移：旧用户 SQLite + 旧 eel_knowledge.json → 备份 / 校验 → 新 SQLite
正常运行：管理网页 → KnowledgeContentService → 显式实例的knowledge.sqlite3
                           ↓ 一个不可变索引快照
AI Knowledge Handler → apps.knowledge.retrieval → 本地 KnowledgeEvidence
```

SQLite 是管理端运行时唯一权威文本来源。运行数据、备份位于所选实例，旧 `apps/knowledge_data` 只是兼容路径。`apps/knowledge/resources` 随包提供默认的 31 条背景资料和可选的溶解氧专题资料。明确执行首次初始化时才会读取对应资源。管理端启动、编辑和检索使用 SQLite。

**新电脑按根目录“开始使用”运行 `Initialize-Management.ps1`，一次建立唯一日常实例并导入31条背景资料，不需要旧机器的数据库或Prototype。原 `--init-data` 仍可显式建立空库。下文迁移仅供已授权的旧数据维护，不是新部署必经步骤。已有库缺失或损坏须停下核查，不能用空库掩盖。**

## 有来源的溶解氧资料

`eel-oxygen-feeding@2` 收录 12 条可回查资料，覆盖日本鳗鲡的溶解氧与摄食、恒定暴露和昼夜波动实验及其适用范围。保留第一版 6 条内容，新增 4 个以 mg/L 记录的实验测点和 2 个以空气饱和度百分比记录的测点。每条资料保留标题、出处和版本。专题的逐条来源、实验条件和旧资料取舍见资源说明。[专题资源说明](../../apps/knowledge/resources/README.md) · [第二版资料](../../apps/knowledge/resources/eel_oxygen_feeding_v2.json)

检索按用户原话中的物种、指标、浓度、单位和区间筛选证据。查询 2.11 mg/L 可找到原文表 1 中日摄食率为 8.9% 的实验点。查询 1–3 mg/L 可找到 2.11 和 2.94 mg/L 两个区间内测点，答复标明覆盖限制。空气饱和度沿用论文中的百分比单位。当前池况由监测工具查询。[Yamagata 等（1983）](https://doi.org/10.2331/suisan.49.1335) · [Rowchai 等（1986）](https://doi.org/10.2331/suisan.52.597)

当系统识别出「请查项目资料」「请从项目资料里查一下」「请参考项目资料」等明确查阅要求，且工具获准时，助手需要取得本轮来源回执才可发布。对于命中结构化规则、且本轮只取得一项专题工具结果的问题，Web 和 QQ 使用程序查得的测点、覆盖范围和出处组装最终正文。网页流式答复在发布核对后展示正文。查资料并对比现场或历史监测值等混合问题，继续按实际调用的工具结果生成答复。

在项目根目录用一个新目录创建审阅实例，再打开网页里的「资料与知识库」。

```powershell
$fisheryReviewRoot = Join-Path (Get-Location).Path 'outputs/rag-oxygen-v2-review'
.\.venv\Scripts\python.exe -I -m apps.management_setup --data-root $fisheryReviewRoot --knowledge-seed curated-oxygen
.\.venv\Scripts\python.exe -I -m apps.management_web --data-root $fisheryReviewRoot --port 8767
```

已经建好的专题实例可直接运行最后一条命令，把 `$fisheryReviewRoot` 改为该实例的绝对路径。专题的首次初始化要求一个新目录。日常实例若要采用专题版，先确认要保留的用户知识，再安排独立迁移。Web 和 QQ 使用同一个检索服务。QQ 保护范围包含本次修改的文件，升级后的首次 QQ 启动可能要求核对并保存现有设置。[QQ 代码指纹与恢复启动](QQ_BOT.md#代码指纹与恢复启动)

## SQLite 格式与版本

Schema `PRAGMA user_version=2`：

| 表 | 作用 |
|---|---|
| `knowledge_records` | 当前知识块：ID、标题、分类、正文、记录版本、状态、更新时间、原始来源、当前内容来源、Evidence ID、原分类/关键词/稳定排序信息 |
| `knowledge_revision` | 整库修订号，在同一写事务内增加，驱动索引重建 |
| `knowledge_metadata` | 迁移来源摘要、迁移版本、原排名使用的病名词表，以及可选专题的版本与适用条件 |

- 内置导入共 **31 块**，稳定 ID 仍是 `builtin-` + 原 chunk ID 的 SHA-256 前24位；Evidence ID 与原资源一致。用户 ID 原样保留。
- `origin=builtin/user` 描述创建来源；导入后两种内容都可编辑、停用、软删除、恢复。
- `original_source_id/version` 永远保留原出处。未编辑导入文本的 Evidence 仍标识 `legacy:eel_knowledge.json / 1.0`，表示出处，不表示运行时仍读该文件。编辑后当前来源变为 `management:knowledge/<id>`，来源版本为实际编辑版本；原始出处不变。
- `version` 是 CAS 记录版本，编辑/状态变更都会增加；导入旧库的版本、状态、更新时间原样保留。原内置无更新时间时保留 NULL，页面不编造时间。
- 不保存完整版本正文历史；软删除可恢复当前正文，不等于恢复任意旧版本。
- 标题120字、分类40字、正文6000字；拒绝空文本/非法控制字符/surrogate。最多200条用户知识、512条导入知识（均含软删除），**全库**正文最多256 Ki字符；列表每页50条，写请求32 KiB，导出最多2 MiB。范围有限，不是文件仓库。

## 检索、并发与模型范围

常规资料继续使用 `apps/knowledge/retrieval.py` 的 TF-IDF 排名，含扩展词、char_wb 2–4、2000 词项、排名加权和 0.04 阈值。专题资料使用 `apps/knowledge/curated_retrieval.py` 按结构化条件匹配。专题信息与启用条目使用同一数据库快照。专题匹配仅使用启用且内容和来源与原始条目一致的资料，编辑版本只进入常规索引。业务 Tool 的参数合同、最多 3 条结果和每条 800 字上限继续适用。

检索事务一次捕获完整启用集合与修订号。构造新索引后发布引用，进行中的检索持有原完整对象；不原地替换一半内容。不把原条目与修改后的替代条目同时加入索引。停用/删除后，下次检索排除；重启继续读同一库。

三个版本彼此独立：

1. **内容来源版本**：逐 Evidence 证明采用哪个知识版本。
2. **索引快照 revision**：整库内容或状态变更后缓存失效，不是模型资格。
3. **模型 Scope**：动态集合仍标识为 `management:knowledge-content / managed-content@1 / portable`。第二版专题的工具来源绑定升级为 `management-project-knowledge@2`，用于区分本轮的检索与发布行为。公共提示词、历史策略、工具入参和调用预算沿用现有合同。真实模型资格仍按对应 Scope 单独验证。

未编辑原始集合的36个固定查询比较 Evidence ID、正文、分数、来源和版本；管理 HTTP/Fake SDK 验证实际新库 Tool Result 进入 Normal/Streaming 下一请求，Gate/清理正常。它们是离线证据，非新增真实模型资格。编辑内容自然可能改变命中，不保证语言质量、事实正确性或养殖/用药建议。

## 知识页面交互（R2D-3D）

- 标题及行内「查看 / 编辑」打开同一详情/编辑板块并定位到可见区域；详情底部右侧「确定」只关闭页面板块，不请求写入，不改变记录版本。返回时保留查询、筛选和列表位置，将焦点恢复至入口；记录因编辑不再匹配时焦点返回搜索框。
- 搜索约300ms防抖，Enter立即查询，清空后按当前分类/状态重查；中文输入法组合文字完成后再搜索。输入控件保留原DOM，结果局部更新；新输入立即作废旧请求，防止旧响应覆盖新结果。
- 搜索/刷新不丢弃编辑草稿；切换记录、新增或取消编辑遇到未保存内容时，沿用页面内明确的放弃/继续编辑确认，不自动保存。
- 新增/刷新保留左侧，右上角导出菜单内选择JSON/Markdown与启用/全部，再下载；Escape或点击页面内其他区域收起。底部「高级功能 · 检索测试」默认折叠，展开后继续使用真实TF-IDF及有限来源结果，不调用LLM。
- 390px列表直接显示标题、状态及查看/编辑，分类、来源和更新时间仍可在详情查看；不要求横向滚动才能操作。本轮只改知识前端与测试，SQLite、检索算法、API、Tool、Scope和真实内容均不变。

离线验收：管理Python 438项、最终前端79项（含知识页16项）、知识存储/HTTP专项25项通过。隔离SQLite浏览器验证查看/确定回列表、同位置同焦点、筛选内编辑、未保存确认、内置/用户内容、停用删除恢复、导出菜单及高级TF-IDF；桌面和390px无页面横向溢出、无控制台错误。

## 迁移操作（须先批准，关闭管理服务器）

在仓库根目录执行。保留现有库与原 JSON，不做移动、删除或覆盖。

```powershell
$knowledgePlan = .\.venv\Scripts\python.exe -m apps.knowledge --dry-run | ConvertFrom-Json; $knowledgePlan
```

默认来源 `outputs/management_web/knowledge.sqlite3`，默认目标 `apps/knowledge_data/knowledge.sqlite3`。Dry-run 只输出数量、状态分布、摘要与计划 hash，不输出正文或用户记录；不会创建目标或备份。来源不存在会拒绝，不自动忽略。

人工核对数量并批准该计划后：

```powershell
.\.venv\Scripts\python.exe -m apps.knowledge --apply --plan-sha256 $knowledgePlan.plan_sha256
```

步骤：只读事务捕获来源 → 校验条目/版本/状态/容量 → SQLite online backup（含已提交 WAL）和原 JSON 备份 → 临时新库单事务导入 → 全字段逐条比较、数量/摘要及 `integrity_check` → 再核对来源计划未变 → 同目录原子 no-replace 发布。

备份位于 `apps/knowledge_data/backups/<UTC时间-随机ID>/previous-knowledge.sqlite3` 和 `eel_knowledge.json`。迁移中的错误回滚临时事务并清除本次暂存文件，保留备份和原文件；目标未发布。已有目标绝不覆盖：相同来源迁移返回 `ALREADY_MIGRATED`，也不会重置新库的后续编辑；来源变了或目标不匹配则拒绝，需人工处理，不能追加导入导致重复。

仅全新安装、确实没有旧用户库时，可显式 `--without-user-db --dry-run`，批准后带相同参数及 `--apply --plan-sha256 ...`。若默认旧库存在，此参数拒绝。自定义 `--source/--target/--legacy-json` 仅为维护者本地迁移与隔离测试，不是 HTTP 参数。

迁移后仍沿用：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen
```

## 查看、导出与备份

- 网页「资料与知识库」按标题/正文/分类/状态查询，打开详情查看完整正文、当前来源、原始来源、版本、状态和北京时间。导入内容与用户内容使用相同编辑与确认操作，修改不回写 Prototype。
- 「导出知识库」选择 JSON / Markdown，以及**当前启用** / **全部（含停用、删除）**。服务端同一只读快照生成下载，包含标题、正文、分类、ID、来源、版本、更新时间、状态及原始出处；固定安全文件名、UTF-8、attachment/nosniff，不接收保存路径。下载不写库、不请求模型、不作为自动同步/导入源。
- `GET /api/knowledge/export?format=json&status=active`（或 markdown/all）继续受本机 Host/Origin/loopback 访问控制。CRUD 还需页面随机 `X-Management-Knowledge`；无账户/RBAC 生产保障。AI 只有只读搜索 Tool。
- 维护者只读查看 schema/数量（不打印正文）：

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; from pathlib import Path; from contextlib import closing; p=Path('apps/knowledge_data/knowledge.sqlite3').resolve(); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); print(c.execute('PRAGMA user_version').fetchone()); print(c.execute('SELECT origin,status,count(*) FROM knowledge_records GROUP BY origin,status').fetchall()); c.close()"
```

定期 SQLite 完整备份使用唯一新文件名，示例失败时不会覆盖已有文件：

```powershell
.\.venv\Scripts\python.exe -m apps.knowledge --backup-to ("outputs/knowledge-backups/knowledge-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".sqlite3") --apply
```

使用 SQLite backup API 而非运行中直接复制主文件，避免遗漏 WAL。JSON/Markdown 是内容交换文件，不包含完整 SQLite 元数据，不能代替数据库灾备。

## 回滚与限制

- 本轮未改真实库，部署前可保留当前服务器进程，审核通过后再迁移并重启。
- 迁移本身从不修改旧库/JSON。若需回旧版程序，先停服、备份/导出新库，再切回审核确认的 R2D-3A 代码基线读取原库；新库后续修改不会自动回灌旧库，不得声称无损自动双向回滚。
- 如需恢复新库备份，先停服、另外备份现库，经人工批准后再置换，不能覆盖未备份的新增内容。
- Monitoring 旧领域依赖留存；本轮不迁移、不读取真实监测 SQLite、Policy、凭据或调用 Provider/NPU。
- 未实现：导出文件再导入、任意文件上传、PDF/Embedding/向量库、历史正文回滚、生产身份权限、全量审计日志、跨进程索引服务器。知识库仍有限容量，TF-IDF相关性及800字片段限制不变。

## 离线验证

溶解氧专题版（2026-11-23）通过完整管理回归，共 1075 项 Python 测试和 163 项 Node 测试。独立审阅实例的网页读取到全部 6 条资料。Web 与 QQ 的模型模拟用例验证检索保留用户原话的浓度，专项用例覆盖精确测点、区间部分覆盖、无匹配、资料停用与编辑。真实 Qwen 回答质量和 QQ 送达留待联调验证。

### 溶解氧专题首轮核对（2026-11-23）

在 `a2eee00` 上只读打开独立审阅库的 6 条资料。三类题通过实际 Web 请求、知识工具和 SQLite 检索，用模拟模型分别返回符合证据的正文与故意越界的正文。QQ Agent 另用隔离资料和模拟送达验证发布行为。24 项相关离线回归通过。真实 Qwen 的工具选择及正文质量待实测。

| 用例 | 工具实际返回 | 回答可以使用的证据 |
| --- | --- | --- |
| 问日本鳗鲡在 2.11 mg/L 的实验摄食率，工具查询被改写为 6–7 mg/L | `OK`，1 条 | 仍命中用户原话中的 2.11 mg/L。原文表 1 实验 I 的日摄食率为 8.9%，适用条件为约 2 g 的日本鳗鲡在 25±1°C 流水水槽中饲育。 |
| 问 1–3 mg/L 是否整个区间都会停食 | `OK`，2 条，均注明部分覆盖 | 2.11 和 2.94 mg/L 两个区间内测点分别为 8.9%/日和 12.8%/日。它们来自同一篇论文的两个实验。卡片还含 3.60、7.26、8.06 mg/L 的背景或对照数据，引用时应明确这些点在所问区间之外。 |
| 问 6–7 mg/L 是否有实验摄食率，工具查询被改写为 2.11 mg/L | `NO_MATCH`，0 条 | 本次专题库未找到该区间内对应的实测点。 |

同一个「溶解氧 1-3 mg/L 鳗鲡 摄食」查询在临时旧库中仍把亚硝酸盐、氨氮和水温排在前三。新版替换了资料和检索规则，以上对照记录的是最终交给模型的证据变化。[新版资料出处](https://doi.org/10.2331/suisan.49.1335)

**检索边界。** 俄罗斯鲟也会误命中日本鳗鲡的资料。原话问生长速度、工具改写为摄食率时，会误命中摄食率卡。`mg/L·h` 也会被误识别成 `mg/L`。这些是需要修复的错配。另有两项属于覆盖不足。卡片正文记载 7.26 mg/L 对照组，但该测点未加入结构化索引。饱和度资料保留原百分比单位，精确查 20% 当前也返回 `NO_MATCH`。

**答复发布。** Web 接受了三条合乎证据的测试正文，也接受了三条模拟的越界正文，包括把 2.11 mg/L 写成停食、把两个测点外推到整个区间，以及无匹配时编造摄食率。Web 的普通和流式请求也都接受了没有调用工具却声称已查项目资料的对照正文。QQ 的离线发布同样接受查完后的三条越界正文，但拦住了没有调用工具却明确声称已检索的对照。现有来源回执记录检索是否完成及是否有证据，逐条正文的事实仍需核实。

### 溶解氧专题第二轮核对（2026-11-23）

第二版回查原论文的测点、条件及出处，补齐部分区间的证据。第一版资料文件和既有实例保留，第二版已在 `outputs/rag-curated-oxygen-v2-2026-11-23` 初始化，可在管理网页审阅。

| 用例 | 第二版实际结果 |
| --- | --- |
| `7.26 mg/L` | 精确找到实验 I 对照测点，日摄食率 12.4%。 |
| `6–7 mg/L` | 部分覆盖，在区间内找到实验 II 的 `6.27 mg/L`，日摄食率 14.1%。 |
| `21.1%` 空气饱和度 | 精确找到实验 1 水槽 1 的测点，原表摄食率 3.76%。 |
| `20–25%` 空气饱和度 | 部分覆盖，在区间内找到 `21.1%` 的测点。 |
| `9–10 mg/L` 或精确 `20%` 空气饱和度 | 无匹配测点。 |
| 俄罗斯鲟、生长速度、`mg/L·h` | 即使模型把查询改写为有效的日本鳗鲡摄食率查询，仍按原问题判定为无匹配证据。 |

测点数值保留原表指标和单位。[恒定溶氧实验表 1](https://doi.org/10.2331/suisan.49.1335) · [昼夜波动实验表 1](https://doi.org/10.2331/suisan.52.597)

使用 Fake SDK 分别经过 Web 普通请求、Web 流式请求和 QQ Agent，注入假设停食、区间外推和无匹配时编造的测试正文。单一专题问题输出了程序校验后的结果，显式查项目资料但未执行工具的用例被来源校验拦截。Web 混合问法仍能运用两项工具结果。真实 Qwen 的工具选择和自由生成答复质量待实测。

本机网页接口读取到 12 条启用资料，六个新增测点逐一精确命中。30 项专项回归通过。管理全量回归中，1085 项 Python 用例通过 1083 项，163 项前端用例全部通过。Windows 演示窗口关闭用例在等待子进程退出时超时，QQ 配对到期用例在清理临时文件时遇到文件占用，这两项单独复测通过。

### 真实 Qwen 验收计划

复用本机研究入口，使用正式应用共用的 Agent 和 Qwen 3.8 Flash。每次重复各用一个新建实例，导入第二版专题资料和模拟水质窗口。计划固定题库、模型参数、资料版本及 SHA-256。报告记录本地答复、实际工具、来源回执、模型请求和用量。研究过程不连接 QQ，网页流式和真实 QQ 投递另作验收。[研究入口说明](QQ_BOT.md#本机真实qwen研究入口)

| 题号 | 检查标准 |
| --- | --- |
| R01 | `7.26 mg/L` 精确命中实验 I 对照测点，引用原表日摄食率 12.4%。 |
| R02 | `6–7 mg/L` 仅引用区间内的 `6.27 mg/L` 测点并交代覆盖限制。 |
| R03 | `9–10 mg/L` 给出无匹配结论。 |
| R04 | 俄罗斯鲟问题返回无匹配，避免采用日本鳗鲡测点。 |
| R05 | `21.1%` 空气饱和度引用原表摄食率 3.76%，保留单位。 |
| R06 | 同一轮取得论文测点和过去半小时的模拟溶解氧数据，比较时清楚交代两个来源和监测覆盖范围。 |

在项目根目录运行离线预检。

```powershell
.\scripts\dev\Test-QQAgent.ps1 -Check -Suite rag -Repeats 1
```

首轮 6 题各做 1 次，计划上限 18 次模型请求，每请求最多 2048 输出 Token。获得当次授权后，以相同参数执行 `-Run`。逐题核对工具选取、检索状态和最终正文。复现偏差时先确定出错的是工具选择、检索，还是正文生成，再用同一道题独立重复 5 次，保留原回答比较。

### 首次真实请求的鉴权结果（2026-11-23）

R01 至 R06 共发出 6 次 HTTP 请求，均收到 DashScope `HTTP_401`。工具执行、可评审答复、QQ 请求和会话提交均为 0，服务未返回用量。原报告保存在 `outputs/agent-research/experiment-20261123T144800Z-c37884badf50/result.json`。原报告的 `completed` 记录计划题目均已处理，`model_expected_tool_mismatch` 把 HTTP 拒绝误算为工具选错。本次真实模型有效样本数为 0。

研究入口现单独统计 `provider_auth_rejected_cases`。记录首个 HTTP 401 后以 `PROVIDER_AUTHENTICATION_REJECTED` 结束，保留该题及完整批次报告。6 项离线回归通过，覆盖鉴权拒绝、普通超时、用量统计与既有题组。先在管理网页的「设置 → API 密钥 → Qwen / DashScope」验证当前凭据。项目使用北京地域的兼容接口，核对 Key 与接入地址的地域和类型后再验收。[百炼 401 排查](https://help.aliyun.com/zh/model-studio/error-code/#401)

专项：`python -m unittest apps.knowledge.tests.test_content apps.knowledge.tests.test_unified_store apps.management_web.tests.test_knowledge_content`；前端：`node --test apps/management_web/tests/knowledge-ui.test.mjs`；管理回归：`python scripts/dev/run_tests.py management`；FAST：`python scripts/dev/run_tests.py fast`。

R2D-3B 验证结果见本轮交付；实际用户知识迁移数量必须在批准后的只读计划中核对，不能把隔离夹具的2条当作真实用户数量。R2D-3A 原只读内置/双来源描述已被本页当前合同替代，Git 历史保留旧实现。

本轮已执行：管理完整回归 **437 Python / 69 Node** 通过（103秒 / 0.87秒）；FAST **165** 通过；旧Prototype知识/Tool **60** 通过；管理资格入口 **44** 离线测试通过。收尾新增未初始化库拒绝测试后，知识专项 **25 Python / 6 Node** 通过，未再重复整套管理回归。浏览器在隔离库验证导入编辑、来源版本、实际新内容检索、软删除/恢复及导出选择；390px无页面横向溢出，未见控制台错误。真实网络请求为0，真实用户库数量尚未读取。备份测试覆盖提交WAL，迁移测试覆盖并发目标抢占和中途失败。
