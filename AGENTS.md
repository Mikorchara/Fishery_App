# Fishery Management 开发规则

- 本仓库是独立管理应用；旧 AI Prototype 不在执行链中。不要修改 `D:\CodexProject\Fishery_AI_Prototype` 或 `D:\Fishery_Project`。
- 保留 `apps.*` 命名空间。依赖为 management_web → ai_service → ai_backend；Monitoring / Knowledge 提供权威业务数据，Simulator 只通过 HTTP 上报。
- Backend 不依赖 Flask、SQLite、Monitoring、Knowledge 或 fishery_ai。禁止复制第二套 Gateway、Tool 循环、Assembler、Ledger 或 Credential Store。
- 以源码为准；Prompt、Tool Schema、Scope、Policy、来源认证、Stop、Deadline、Commit Gate 的变更需要明确任务授权与离线回归。
- 保护不可替代数据，破坏性操作先征得批准。Windows 路径用 LiteralPath；路径中的下划线不转义。不修改工作区外文件，除非用户明确授权。
- 不读取/输出真实密钥。Credentials 使用原独立私有 Store；业务数据、Settings、Policy 和 Trace 不得进入 Git。禁止源码根 .env 回退、load_dotenv、浏览器保存密钥。
- 自动测试只用虚构凭据、Fake SDK、自包含固定夹具和临时数据库。真实 Provider/NPU/连接测试须用户主动批准或亲自执行；安装 Python 依赖不等于模型请求。
- 开发环境：Python 3.11+、本仓库 .venv、Node。安装 `python -m pip install -e .`；独立测试 `.\.venv\Scripts\python.exe -I scripts/dev/run_management_tests.py`（禁止导入旧包）。不要使用旧项目的虚拟环境、editable 安装或 PYTHONPATH。
- 测试 TEMP/TMP 必须指向本仓库忽略目录，例如 outputs/test-tmp；不要让隔离测试写正式 `%LOCALAPPDATA%\FisheryManagement`。
- 启动/初始化必须明确选择数据根。缺失已有库应报错；不得初始化空库掩盖迁移遗漏。真实数据迁移与凭据身份处理需独立批准。
- 普通启动、刷新和测试不得自动调用模型；失败不得自动重试、切换 Provider 或传输方式。
- 行为变更补针对性测试与中文文档；不要为目录美观增加框架。详细规则见 apps/AGENTS.md，操作见 apps/docs/BUILD_RUN.md。
- 不自行 commit/push；初始基线提交也须用户批准。
