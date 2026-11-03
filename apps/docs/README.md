# Fishery Management 文档

交接版文档按“上手、使用、开发”阅读。当前事实以源码、固定合同和新验收结果为准；本机研究能力不等于生产发布。

## 组员先看这四份

| 文档 | 解决什么问题 |
|---|---|
| [部署与配置](DEPLOYMENT.md) | 新电脑建环境、选实例、配置Web/QQ、离线检查和交接验收 |
| [日常启动](BUILD_RUN.md) | 两终端/三终端、带视频入口、场景与停止 |
| [网页使用](USER_GUIDE.md) | 页面、AI工具、事件、知识、设置 |
| [技术路线（组员版）](TECHNICAL_ROUTE_TEAM.md) | 汇报时如何解释整体系统 |

制作PPT看 [PPT Agent版](TECHNICAL_ROUTE_PPT_BRIEF.md)。对接设备先看 [当前模拟报文简略版](DEVICE_INTERFACE_QUICK.md)，真实设备与视频服务属于 [后续规划](deep-dive/plan/REAL_DEVICE_INTEGRATION.md)。

## 维护和开发

- [运行维护、数据库备份/升级、日志与回滚](deep-dive/OPERATIONS.md)
- [QQ Hybrid、预算、权限、会话与通知限制](deep-dive/QQ_BOT.md)
- [事件周期、确认、人工结束与永久删除](deep-dive/EVENT_MANAGEMENT.md)
- [实验评分规则](deep-dive/EXPERIMENTAL_WATER_SCORE.md)
- [历史趋势图](deep-dive/HISTORY_CHART_UI.md)
- [统一监测协议与服务合同](INTEGRATION.md)
- [模块目录与职责](STRUCTURE.md)
- [AI Backend与Tool开发](deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)
- [知识内容、导出与维护](deep-dive/KNOWLEDGE_CONTENT.md)
- [下一步与已知缺口](ROADMAP.md)

仅资格维护者需要 [Streaming技术资格](deep-dive/STREAMING_QUALIFICATION.md)、[历史Tool技术资格](deep-dive/HISTORY_QUALIFICATION.md) 和 [人工真实资格脚本](../../scripts/manual_real_tests/README.md)。这些历史技术记录不授予当前源码新的联网许可。

重复阶段验收、旧迁移计划和PRE_MIG3副本已从日常docs中清理；当前约束合并进上述主题。原提交留在Git，清理前副本与映射保存在本机outputs中的独立维护目录，不加入交付源码。工程约束见 [AGENTS](../AGENTS.md)。
