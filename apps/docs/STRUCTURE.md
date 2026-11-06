# 目录与模块职责

本页只列交接需要的稳定边界，不维护容易过期的逐文件清单。全部运行命名空间为apps.*，不安装旧fishery_ai。

```text
Fishery_Management/
├── pyproject.toml / README.md / AGENTS.md
├── 开始使用.md                   新下载源码后的逐步操作
├── sample.mp4                    获准的本地录像；源码可跟踪，Wheel不包含
├── apps/
│   ├── management_paths.py        统一业务数据路径
│   ├── management_process.py      指定实例的进程所有权保护
│   ├── management_web/            Flask HTTP/SSE、设置API、静态UI
│   ├── ai_service/                业务Assistant、装配、资格、来源与Policy
│   │   ├── business_tools/        当前/历史/知识与可选实验评分
│   │   ├── runtime/               业务Prompt/History/来源/发布合同
│   │   └── resources/             固定候选与准备合同，不是用户批准
│   ├── ai_backend/                通用模型Gateway、SDK、工具循环、取消与资源门禁
│   ├── monitoring/                观测、规则、事件、Repository、Service、显式迁移
│   ├── knowledge/                 知识CRUD、检索、导出和显式维护
│   ├── device_reports/            独立报告HTTP接收/存储；bridge.py本机同步到Monitoring设备事件
│   ├── simulator/                 独立HTTP生产端，不直接写库
│   ├── qq_bot/                    独立Gateway、权限、会话、预算、交付和通知
│   └── docs/                      根目录仅保留五份常用文档
│       ├── guides/                详细部署与网页使用
│       ├── development/           数据接口与集成合同
│       ├── presentations/         组员技术路线与PPT材料
│       └── deep-dive/             专题技术、维护与未来规划
├── scripts/
│   ├── dev/                       两/三终端、带视频、停止、离线测试
│   ├── maintenance/               已有受控旧数据迁移，不是日常初始化
│   └── manual_real_tests/         维护者人工真实资格测试
└── outputs/                       忽略：测试实例、配置、日志、备份、批准与报告
```

## 依赖与执行链

- Web → AI Service → AI Backend；Backend不能反向依赖Web、SQLite、Monitoring或QQ。
- AI Service通过显式Registry绑定现有只读业务Tool；Policy、Scope、来源、期限和Commit控制执行。没有第二套Agent。
- Monitoring/Knowledge提供权威数据；网页和Tool共用它们，不各建一份current状态。
- Simulator只通过带本机令牌的HTTP批次上报，由Monitoring事务写入。
- 设备报告走独立接收器与报告库，Web桥接到`monitoring/device_events.py`，复用事件管理和通知；不走Simulator ingestion，不新增数据库表。
- QQ独立进程复用相同Service与Backend，通过只读Repository看一个批准实例。Bot退出或SDK隔离不会传播到Web进程。
- device_reports接收器只写独立报告库；Web桥接负责Monitoring设备事件。设备视觉报告不进入当前水质AI来源。
- 视频播放器独立于统计和事件，不推断画面内容。

## 需要改哪里

| 任务 | 首先看 |
|---|---|
| 页面布局 | management_web/static；不复制监测阈值 |
| 新业务Tool/Prompt | ai_service/business_tools、runtime；先读开发指南 |
| Provider取消/清理 | ai_backend/openai_compatible_adapter.py、sdk_resources.py、execution.py |
| 事件/ACK/周期删除 | monitoring/events.py、event_families.py、event_handling.py、event_cycle_deletion.py |
| QQ配置、网页配对和启动 | ai_service/qq_settings.py、management_web/qq_settings_api.py、qq_bot/private_pairing.py、management_configuration_bridge.py、management_run.py；scripts/dev/Start-*.ps1 |
| 数据库升级 | monitoring/migrate.py；只显式维护，不在启动中调用 |

数据根与源码目录分开，凭据又是独立私有Store。四个日常cmd共用 `outputs/qq-m3-real-test`；`apps/management_setup.py` 和 `Initialize-Management.ps1` 负责首次显式初始化，`knowledge/resources` 提供31条初始背景资料。QQ后续通过网页“QQ机器人”设置接入同库，见根目录[开始使用](../../开始使用.md)。不要为了目录整齐挪动实际数据库。

QQ Web-Agent新增装配：`ai_service/channel_management_agent.py` 与 `channel_agent_presentation.py` 复用原四Tool/Receipt和2/2/3循环；`qq_bot/knowledge_source.py` 只读打开同一批准实例的知识库，`agent_conversations.py` 沿用原RAM预算、revision与CAS。原Web默认配置及旧QQ单轮合同不变。
