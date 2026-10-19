# 独立管理项目路线

## 当前

MIG-1 领域依赖闭包、MIG-2独立发行/数据路径、MIG-3新项目工程准备。保留新侧Backend、监测/模拟、知识内容、Settings、三个只读Tool和Qwen本地Normal/Streaming范围。迁移不新增模型资格。

## 下一步

1. 用户验收代码与离线结果，批准初始Git基线提交。
2. 单独批准真实数据迁移：停止写入方、安全备份、两个SQLite完整性与内容校验、Settings/Policy选择保留、原子发布，防止空库掩盖遗漏。
3. 明确独立Credential身份与用户重新配置/受控迁移，不能随数据库复制密钥。
4. 用户亲自验收正式实例的Knowledge、Monitoring、Settings和三个Tool；真实连接逐次明确操作。
5. 业务开发：视觉/历史领域分析、设备接入、告警、权限部署等按实际需求推进；新Tool/预算/Scope仍需相应测试与授权。

暂不开展Agent框架、Runtime重写、包命名全面调整、Settings Store基础设施整理或RAG算法替换。
