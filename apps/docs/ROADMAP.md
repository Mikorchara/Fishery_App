# 独立管理项目路线

2026-10-30：选择性加入 Prototype 深蓝主题、浏览器本地切换偏好与必要静态测试；保留浅色默认及原启动/业务/数据路径。前端121项与Web HTTP11项通过，本轮不含本地视频功能。

2026-10-29 M3：独立 Bot 配置/进程许可、真实类型化 Gateway/SDK 装配及三终端薄编排完成；仅 Mock/新建隔离实例验收，QQ/Qwen 真实联网仍待用户。原启动器保留，Bot 故障不停止 Web/Simulator。[操作与验收](deep-dive/M3_MANAGEMENT_STACK.md)。

2026-10-29 M2：独立 QQ Hybrid 的 Fake-only 装配、Monitoring-only 工厂、额度/历史/交付与跨进程隔离验证完成；默认禁网，不启动后台 Bot。真实配置/资格/启动留待 M3。[验收与边界](deep-dive/M2_QQ_HYBRID_OFFLINE_ACCEPTANCE.md)。

2026-10-29 M1：Repository 只读、SDK 资源门禁和默认不启用的内部装配扩展完成，609 Python / 116 Node 通过；Web 仍要求 Knowledge，无 QQ/Hybrid 入口。[验收与回滚](deep-dive/M1_SHARED_SAFETY_ACCEPTANCE.md)，M2 待人工审批。

2026-10-24：复核并选择性同步失联提醒人工结束，保留监测状态/证据，重启持久、新可靠HIT重新提醒；补修校时回退的操作排序。继续使用Schema v2，不触碰真实数据库。[边界与预览](deep-dive/EVENT_MANUAL_END.md) · [验收](deep-dive/MANUAL_END_SYNC.md)。

2026-10-23 EVT 收尾：选择性同步 ACK v2、风险周期列表、二态确认、可靠结束周期及 ACK 显式永久删除、恢复蓝色标签与快降慢升场景。正式/演示库仍为 v1，禁止自动升级；须人工批准维护后启动。[核查、兼容及验收](deep-dive/EVT_SYNC_ACCEPTANCE.md)。

## 当前

2026-10-23：经用户批准，选择性同步 Prototype EVT-1/EVT-2 及文案收尾：视觉三窗恢复、风险族等级关联、首页活动提醒、关注区间五档筛选和受控历史硬删除。SQLite Schema 不变，未加入人工确认/关闭/暂缓；Management 保留独立启动与数据路径。[事件管理边界](deep-dive/EVENT_MANAGEMENT.md)。

2026-10-21：双击演示在 Simulator 窗口先选择六场景，Enter 默认、0退出；原非交互 CLI 保持兼容，复用 Job/启动锁和原模拟器。BUILD_RUN 增加快速入口，项目差异见 [启动比较](deep-dive/LAUNCHER_COMPARISON.md)。

2026-10-21：经 Prototype 实验与人工认可，选择性同步五档历史范围、分档节点、三指标归一化与原值 Tooltip；首页两列底边对齐、事件底部通栏，保留 Management 品牌、启动器和数据隔离。实现边界见 [图表说明](deep-dive/HISTORY_CHART_UI.md)。

2026-10-21：新增双击演示入口 `scripts/dev/启动演示系统.cmd`，复用原启动器打开两个终端并回收整组子进程；`outputs/demo-instance` 首次只复制正式知识，后续保留编辑。网页名称更新为“AI 监测系统”，模型试用范围不变。

MIG-1 领域依赖闭包、MIG-2 独立发行/数据路径、MIG-3 独立项目与初始提交、MIG-4 业务数据迁移已完成。MIG-5 凭据准备与真实网页基本验收完成状态由用户确认；本轮文档整理不重做真实连接或生成新的资格记录。

当前保留独立 Backend、统一监测/模拟、知识内容管理、Settings、三个只读 Tool 和 Qwen 本地 Normal/Streaming 范围。迁移不新增模型资格；`PROTOTYPE` 规则与 `local_experimental` 模型范围仍保留原边界。日常使用见 [使用指南](USER_GUIDE.md)。

## 下一步

以下是待选择的业务方向，不表示本轮批准或实现：

1. 真实设备接入：明确设备身份、上报质量与权限后，替换模拟生产端；网页与 Tool 继续共享 Monitoring。
2. 历史领域分析与视觉能力：基础历史统计已实现；持续异常、恢复判断和视觉 Tool 仍需独立定义证据要求，不让 LLM 猜测。
3. 运维与业务闭环：完整实例备份/恢复、告警处理、媒体存储和运行日志；保留既有迁移备份，不重复迁移已存在的正式实例。
4. 权限与部署：生产认证、多用户和远程部署需要专项安全设计，本机访问控制不能直接当作生产权限。
5. 模型与检索扩展：自定义模型、高级 RAG 或其他模型组合按需求评估，不自动继承已有 Qwen 本地许可。

暂不开展Agent框架、Runtime重写、包命名全面调整、Settings Store基础设施整理或RAG算法替换。
