# 独立管理项目结构

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
│   ├── monitoring/                # 事实、规则、Events、SQLite、历史统计
│   ├── knowledge/                 # 内容 CRUD、SQLite、TF-IDF、显式迁移
│   ├── simulator/                 # Scenario、10秒采样窗口、HTTP上报
│   └── docs/                      # 当前操作、开发合同与历史设计
├── scripts/
│   ├── dev/                       # 一行启动、独立管理测试
│   ├── packaging/                 # MIG-2发行模板/白名单staging检查
│   ├── qualification/             # 管理专用显式资格CLI
│   └── manual_real_tests/          # 用户主动真实测试，默认dry-run
├── .venv/                         # 忽略，本项目独立环境
└── outputs/                       # 忽略，隔离实例/测试/构建/报告
```

管理依赖为 Web → AI service → Backend；AI service 的业务 Handler 查询同一 Monitoring / Knowledge 服务。Monitoring 不依赖 AI；Backend 不依赖 Flask、SQLite 或业务模块。执行循环不复制。

正式数据将放用户应用数据目录，与代码/凭据分离；本轮只使用 outputs 下隔离实例。没有 src/fishery_ai、旧根 tests 或旧 outputs。知识固定 JSON 仅为测试与资格夹具，正式内容唯一权威为所选实例 knowledge.sqlite3。

Tool、Prompt、Scope 和安全边界见 [开发指南](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。当前命令见 [BUILD_RUN](BUILD_RUN.md)；旧目录地图存于 history/，只是来源记录。
