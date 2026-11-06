# 当前水质实验评分

Management 已选择性同步 Prototype 人工认可的评分实现。`score_current_water_quality` 是程序计算的只读 Tool，不是模型自行打分，也不是专业标准。

## 使用

在 Management 根目录启动 `scripts/dev/启动视频演示系统.cmd` 或 `scripts/dev/启动QQ视频演示系统.cmd`。这两个新入口显式携带评分开关；原来的两个无视频入口不改默认行为。手动使用 `run_local.ps1`／`Start-ManagementStack.ps1` 可加 `-ScoreTrial`，不能同时加 `-NoAssistant`。

进入「系统设置 → Assistant Tool 授权」，勾选「水质实验评分（非专业标准）」并保存。使用 Web 固定 Qwen Preset，核对本次发送后提问“请给当前水质实验评分，并解释依据”。页面、授权保存和启动开关本身不调用模型。旧QQ模式不增加评分；新网页保存的Web-Agent配置可在独立Bot Policy、Scope和运行批准下使用同一只读评分工具，详见[QQ说明](QQ_BOT.md)。

## 评分依据

只复用本窗口 Monitoring 已评估的 WATER_RISK HIT／CLEAR，不改诊断阈值。

| 指标 | 权重 |
|---|---:|
| 溶解氧 | 50% |
| 水温 | 25% |
| pH | 25% |

各指标全 CLEAR 得100分，warning 得60分，critical 得20分，极低溶解氧 HIT 得0分。同一指标取最严重等级，不重复扣分。先加权，再按最严重信号将总分封顶：warning 79、critical 39、极低溶解氧19。

例如水温、pH均 CLEAR，溶解氧严重低氧 HIT：加权原分60，经严重信号封顶为39。100分仅代表本窗口已评估规则未见异常，不证明鱼群健康、无疾病、长期稳定或适合养殖。

## 不可评分

三项必须完整、有效、新鲜、在线，并具有完整可靠规则证据。缺测、部分有效、无效、过期、离线或规则不足返回 `NOT_SCORABLE`，不补满分、不归一化剩余权重、不借历史数据。无观测返回 `NO_DATA`。两者均无总分和等级。

结果保留来源、设备、批次、观测／接收／评估时间、质量、新鲜度、连接状态及规则版本。查询不重新采样，视频也不是评分输入。

## 权限与兼容

- 独立合同 `management-score-tool-trial@1`；算法 `management-water-score@1`，Source `management-water-score-source@1`。
- 固定 Qwen、Normal／Streaming、原有有界工具循环，最多2 Tool／2轮／3次模型请求，仍受原配置预算与每次发送确认约束。
- 固定资源默认 `enabled=false`，显式开关才启用 `local_experimental`；`qualification_id`、`validated_at` 均为空，不借用三工具发布资格。
- 未选评分时走原工具装配；Web 仍要求 Knowledge，旧Monitoring-only QQ不注册评分；新Web-Agent QQ使用独立的四工具装配，不改变Web默认开关。
- Source Gate 验证新评分结果；“已评估但不可评分”不生成已取得分数的 Receipt。旧 payload 的兼容语义保留。
- 不写新表、不改 Schema 或业务规则，不迁移设置或凭据。停用可在下次启动省略 `-ScoreTrial`。

Management 使用合成 SQLite、Fake SDK 验证 Normal／Streaming、Source／Commit、SDK关闭、规则边界、不可评分、跨设备注入、Scope及Policy失效。Prototype 的真实截图不等同于 Management 已完成真实模型验收；后者仍由用户执行。
