# MIG-3：独立项目迁移记录

> 历史阶段快照：本文的“本轮未迁移”“待初始提交”“后续”等描述指 MIG-3 结束时，保留作为当时证据。当前已有独立提交 `6e67202` 与 MIG-4 提交 `9666ae7`；业务数据迁移见 [MIG-4](MIG4_DATA_MIGRATION.md)，MIG-5 凭据及基本网页验收由用户确认完成。日常操作改看 [使用指南](../USER_GUIDE.md) 和 [BUILD_RUN](../BUILD_RUN.md)，不要按本文旧待办重复初始化或迁移。

源基线：MIG-1 `dfa60db`、MIG-2 `2b099cf`；源工作树干净。新项目位于 `D:\CodexProject\Fishery_Management`，采用独立 Git 初始基线，不引入旧提交历史。

## 复制与调整边界

- 保留 apps.*、六个正式模块、management_paths、固定资源、独立测试/夹具和管理文档。
- 未复制旧 src/fishery_ai、根 tests、任何业务 SQLite、Settings、用户 Policy、Credentials、备份或敏感 Trace。
- 逐文件复制前后哈希清单保留于忽略目录 `outputs/mig3/source-manifest.json`；其中不含业务数据。
- 不带走七个仅旧包差分/历史 Runtime 迁移/旧资格测试模块；另移除九个只用于旧包或旧资格计划对拍的测试方法。新管理测试原有459项保留，不通过跳过失败测试掩盖遗漏。
- 新项目 run_tests 只发现管理测试，原混合工程的 PRODUCT/QUALIFICATION 入口不再作为本仓库命令。人工资格 CLI 仍独立、默认 dry-run。
- 资格工具原来五处旧包资源定位改用已随新侧带走的固定知识夹具；夹具字节不变、来源版本不变，正常 Web 不加载它。开发工具不进入 Wheel。
- 知识迁移 CLI 不再推导旧仓库路径，source/target/legacy-json 需明确给出。正常应用不调用迁移 CLI。
- 除这些工程/显式维护入口调整，正式运行代码、Prompt、Tool Schema、Scope、预算及发布资源按原样复制；没有新增模型资格。
- 初始Git全量检查发现六处来源/裁剪测试的文件末尾空行，已仅在新项目清理；涉及Python文件均比较AST完全一致，未调整Settings Store或知识导入逻辑。

## 数据与凭据

本轮只用本项目 outputs 下的隔离测试根。正式 `%LOCALAPPDATA%\FisheryManagement` 未作为实例打开或初始化；旧工作区真实数据和密钥未读取或迁移。

管理启动仍要求明确选择数据根，详见 [BUILD_RUN](../BUILD_RUN.md)。新实例初始化是空白数据库，不导入源仓库数据。保留旧路径兼容解析仅为维护/既有合同，日常操作不能靠它发现或迁移数据。

Credentials 私有 Store 与身份算法保持原实现，包括私有目录的历史产品名称；新项目根散列与旧项目不同，不自动沿用旧密钥。真实数据迁移、凭据重新配置和正式实例启用均留后续批准。

## 验收

所有验证只用 Fake Provider 和虚构数据；安装依赖不等于调用真实模型。

| 检查 | 结果 |
|---|---|
| 独立环境 | 本项目 `.venv`，Python 3.12.14，依赖按原约束从公开包索引独立安装；openai 2.54.0；pip check 通过 |
| 完整管理回归 | 459项Python通过（108.423秒）、87项Node通过 |
| 管理FAST | 25项通过；不包含旧Prototype测试 |
| 正式Wheel | setuptools 84、满足>=68要求；110项文件；18个正式资源与来源逐字节相同；无旧包、测试、development、数据或Trace |
| 安装包实际运行 | 移除本项目editable后安装Wheel，从-I进程验证所有生产模块来自site-packages；旧fishery_ai缺席 |
| Fake HTTP/SSE | Direct/单Tool/双Tool，Normal与Streaming六条协议/Steps/Usage/Ledger/安全DTO/revision/提交指纹与固定基线完全一致 |
| 三工具安装包专项 | Current/History/Knowledge选择、顺序双Tool、授权/预算、Stop/断流/Trace等10项通过 |
| PowerShell真实进程 | 隔离实例、18766端口、low_oxygen场景、NoAssistant，HTTP读取到simulator数据；重复启动拒绝且不影响原进程 |
| Ctrl+C | 监督进程执行清理；其两个子进程和监督进程全部退出，端口关闭（PTY中断返回码为1，不是后台进程残留） |
| 资格入口 | history valid-history、streaming current-water仅Dry-run，网络请求均为0；没有资格升级 |
| 静态检查 | 六包独立导入、150份Python AST、251个文档本地链接通过；独立数据与正式目录元数据隔离检查通过 |

验收后恢复本项目自己的editable安装，便于继续开发；没有旧仓库editable或PYTHONPATH。依赖按原允许范围安装，部分间接依赖小版本比来源环境新；Fake协议差分通过不等同于新的真实Provider资格。

构建/测试/包安装日志与可复查的脱敏清单放 `outputs/mig3/`（Git忽略）。隔离示例实例在 `outputs/acceptance-instance`，含模拟数据、空知识库；不是正式业务数据。所有服务已停止。

Git基线仅在上述验收通过后初始化并准备审阅；没有初始commit、remote或push。源仓库保持原HEAD及干净工作树。

新仓库分支为 `codex/mig3-baseline`，228个文件已暂存待用户审阅；程序/测试/资源、25份管理文档和12份脚本在同一清晰基线中。18个正式资源的暂存Git blob也与来源HEAD一致。虚拟环境、隔离SQLite、构建和测试日志均被忽略。完整路径清单在 `outputs/mig3/staged-summary.json`，不包含真实业务数据。

## 后续

先由用户验收新项目并批准初始提交，再设计真实数据备份/完整性校验/原子迁移。不得使用初始化空库掩盖迁移遗漏。旧仓库完整保留，不让两个项目自动同步数据库或凭据。
