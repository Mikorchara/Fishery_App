# M1：共享安全基础与兼容性验收

日期：2026-10-29。仅 Management；没有 QQ/Hybrid、人工审核入口，没有真实模型、凭据或业务实例访问。本轮不提交，M2 等待另行批准。

## 1. 基线与结果

| 项目 | 结果 |
|---|---|
| Management 起点 | codex/mig3-baseline / 689f0f31f0a0a33d1c1ae95b5df9dcc0d5a22065，工作树干净 |
| Prototype 参考 | main / dcb70a243199f3e534904b8d7fd99d323feacc6f，干净且全程未修改 |
| 环境 | Python 3.12.14，OpenAI SDK 2.54.0，httpx 0.28.1，Flask 3.1.3；依赖和 pyproject 未改 |
| 修改前完整回归 | 575 Python / 116 Node，全部通过，Python 207.102 秒 |
| 修改后完整回归 | 609 Python / 116 Node，全部通过，Python 200.795 秒 |
| 专项 | 123 项通过，涵盖 SDK 分片/取消/资源、Repository、内部装配、Service、Web Streaming |
| 额外跨功能验证 | 同一 Web AI 预算隔离后，第二次 AI 请求拒绝；模拟数据继续入库，监测/事件 GET 均 200，事件仍生成 |
| 打包补充验证 | 原白名单 staging 包含 sdk_resources.py；新隔离进程可从 staging 导入 Adapter，无旧包/QQ 或业务数据库 |

使用本仓库入口：`.\.venv\Scripts\python.exe -I -B scripts/dev/run_management_tests.py`。TEMP/TMP 仅在测试进程中指向本仓库 outputs/test-tmp。原测试无删除、无跳过；新增 34 项为 SDK 18、只读 10、装配 5、HTTP 隔离 1。测试覆盖 Normal/Streaming、三只读工具、监测/事件、Knowledge、Simulator、Windows 两终端/端口冲突/关闭回收及发行 staging；不是实际用户实例或付费模型验收。

证据目录：`outputs/test-tmp/m1-20261029T122044/`。baseline.json 保存版本、起始 Git 与源码 SHA；baseline-tests.log 和 verified-tests.log 为完整前后结果；targeted-verified.log、isolation-probe.log、packaging-probe.log 为专项。verified-source-freeze.json 保存最终执行源码摘要。

最终源码冻结核对、Python AST、31 条本地文档链接和 git diff --check 通过。verification.json 保存 16 个改动文件摘要；full-m1.patch 保存完整正向差异，可先做反向 --check 以审阅回滚，本轮只检查、不执行回滚。没有生产实例版本检查或数据库备份，因为本轮完全不访问实际业务库。

## 2. 实际文件与边界

| 文件 | 内容 |
|---|---|
| apps/monitoring/repository.py | read_only=False 默认；显式只读绝对路径、SQLite 只读连接与查询预算 |
| apps/ai_backend/sdk_resources.py（新增） | SDK 租约、关闭状态、并发上限、进程内不可重置的故障隔离 |
| apps/ai_backend/openai_compatible_adapter.py | 按差异块合入 Client/Stream 关闭、取消及线程回收检查；另修复启动前超时的租约滞留 |
| apps/ai_backend/execution.py | Handle 资源状态、Commit 前关闭检查、未释放资源不能按终态/TTL 裁剪 |
| apps/ai_service/runtime/assistant.py | 内部可选 single_round_prompt，默认 None；复用原上下文和 Agent |
| apps/ai_service/business_tools/registry.py | 内部 include_knowledge=True 默认；显式 False 可不注册 Knowledge |
| apps/ai_backend/tests/test_sdk_resources.py（新增） | SDK 关闭、取消、不合作 I/O、预算/Registry 隔离及启动前失败 |
| apps/monitoring/tests/test_read_only.py（新增） | 合成库禁止写入/升级、并发、快照与资源上限 |
| apps/ai_service/tests/test_m1_composition.py（新增） | 默认与显式装配、原 Commit、Web Knowledge 要求 |
| apps/ai_backend/tests/test_assembler.py | 独立用例预算及精确清理错误码；原分片、关闭、零重试断言保留 |
| apps/management_web/tests/test_streaming.py | 独立用例预算及同一预算隔离后拒绝下一请求的 HTTP 验证 |
| apps/ai_service/tests/test_service.py | Web 拒绝注入内部 Prompt、工具装配和渠道授权字段 |

两个既有 SDK 文件按 diff hunks 修改，没有整体覆盖 Backend。Repository 没有移入 Prototype 的 capture_events/事件查询扩展。ManagementAssistantService 本身、领域 Service、Schema/规则/事件状态机、Web 页面/路由、Windows 启动器、路径、Settings/Policy/凭据装配和依赖均未改。

## 3. Repository 只读合同

- 仅显式 read_only=True 且传入绝对文件路径；缺库、空库、v1、未知 Schema 或损坏拒绝。无父目录/数据库创建、迁移、修复或实例回退。
- mode=ro + query_only + authorizer；禁止 INSERT/UPDATE/DELETE、DDL、ATTACH/DETACH、VACUUM、写 PRAGMA 和关闭 query_only。
- 短连接：锁等待 0.25 秒；进度预算 2 秒或 2,000,000 VM 步；SQLite 单值长度上限 262,144 字节。进度回调不等于实时操作系统硬截止。
- 默认读写连接继续支持上报、事件与历史。测试包含 rollback journal 并发、WAL 同一事务快照和后续提交可见性；不对活动库使用 immutable。
- 只读保护业务记录/Schema，不宣称 SQLite WAL 的共享内存旁文件没有元数据活动。
- Repository 不代替群权限、设备白名单与路径身份认证；M2 装配仍须冻结并验证配置。M1 未打开任何现有业务实例，也未核实其实际 user_version。

## 4. SDK 生命周期与兼容

正常路径沿用原 Adapter、RequestHandle、ToolCallingService、Source/Commit Gate。请求编码、工具循环、模型次数/Token/Deadline 不改。只有 Client/Stream 关闭、Task 完成且请求线程退出才能标为 CLOSED；取消信号、本地 I/O 关闭、线程退出、远端计算停止分别记录，远端始终 unknown。

清理失败返回 SDK_CLEANUP_FAILED / SDK_CLEANUP_TIMEOUT；后续 SDK 请求以 SDK_RESOURCE_QUARANTINED 拒绝，不能新建 Client。失败 Handle 不因 TTL/普通终态裁剪释放占用；Commit 前不能把未确认清理视为成功。请求状态在存在实际 SDK 租约时增加 sdk_resources，原字段保留。正常成功语义保持；故障错误码更精确、故障后拒绝新 SDK 调用属于本轮授权的安全增量。

额外修正：来源实现先预留租约再检查 deadline，离线复现启动前 TOTAL_TIMEOUT 后 active=1。Management 将预留移到队列/deadline/线程对象准备之后、线程 start 之前；新测试验证零 Client、零遗留租约。此处 Management 有自己的修复，未来同步不能被 Prototype 文件覆盖；Prototype 本轮未改。

Python 仍不能可靠强杀不合作线程，没有新增 SDK 子进程隔离。既有 daemon 标志不代表清理成功；调用方有界返回后保留失败隔离，运行中没有 reset。重新启用须有审查的进程退出/重启；不承诺远端停止计费。SDK 全局预算在每个进程中独立，未来独立 Bot 不会共享 Web 的隔离对象。

## 5. 默认关闭、权限与 Scope

- 没有 apps.qq_bot、QQ/Hybrid CLI、新后台 worker、启动钩子或 Web 路由；没有 can_send/can_deliver 放行。
- Web 仍要求 Knowledge，构造合同未改；没有提前实现 Monitoring-only Service 工厂。
- 内部 Prompt 默认 None，工具装配默认 include_knowledge=True；现有 Web 不传新参数，公开请求拒绝注入。
- SDK 安全检查作为基础保护生效，不是默认关闭的功能开关。只读 Repository 分支须明确选择。
- 公开 Scope/资格资源、Policy、默认 Prompt、Tool Definition 保持原字节或合同，未改旧批准/used/回执。SDK 源码 SHA 已变化，旧真实记录不等于新实现联网资格；本轮只有离线兼容证据。M2 需要独立 Management 渠道 Scope，实际绑定 Adapter、资源合同、Prompt、Tool、预算和身份。

## 6. 中间失败记录

中间日志全部保留，不冒充最终通过结果：首轮专项 3 项涉及旧 SDK_ERROR 断言及独立用例共用故障预算；下一轮 1 项为合成报文时钟未推进，修正夹具后通过。首轮完整 final-tests.log 为 142 failures / 21 errors，主要是 Assembler 两个清理故障用例留下全局隔离，造成后续级联拒绝，且仍断言旧错误码。

Assembler 和 Web 故障测试现按独立测试进程语义使用独立预算；同一预算内不恢复隔离，并有后续请求拒绝验证。没有在生产代码中重置门禁、重试或跳过测试。最终固定源码重新跑完 609/116，见 verified-tests.log；不要把中间 final-tests.log 当成最终结果。

## 7. 回滚与 M2

本轮不提交。保留基线 SHA、依赖和源码摘要、完整差异补丁；后续如有其他改动，先核对清单和补丁反向检查，不能盲目覆盖或执行 reset/clean。回滚只撤销 M1 源码/测试/文档及新增文件，不恢复/初始化/覆盖业务库，不清理 outputs、批准或历史。SDK 回滚须重启对应 AI 进程，不能运行中清除隔离。

M2 单独审批：QQ 可选依赖及独立启动；Gateway/权限/有界会话/RunConsent/Delivery；Management 专属 Monitoring-only 类型化授权工厂和 Hybrid Scope；新建合成库/Fake 全链路；保留已有默认 Web 与正式数据路径。首版只允许当前水质只读 Tool，不含人工审核、事件写入、Knowledge/历史 AI Tool。凭据配置、现有实例读取及 QQ/Qwen 联网继续独立批准。
