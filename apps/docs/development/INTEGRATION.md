# 统一监测协议与集成边界

日常使用看BUILD_RUN；本页面向编写生产端、只读消费者和测试的开发者，不是允许真实硬件接入的授权。

## 1. 当前执行链

Simulator → 带本机接入令牌的HTTP批次 → MonitoringService → DomainAnalysis/EventService → 单事务Repository。Web和AI Tool使用同一Service读取；QQ是独立进程的显式只读Repository，不复制SQL或规则。Monitoring当前观测源仍为SIMULATOR。独立 `apps.device_reports` 已支持开发板报告HTTP接收及专用存储，Web只读展示；不接入Monitoring事件/Tool，真实视频/NPU尚未合入。设备联调启动见 [连接步骤](../DEVICE_INTERFACE_QUICK.md)。

后端apps.ai_backend只处理通用模型协议、执行、工具循环、取消和资源；业务Prompt/Registry/Policy/Source/Commit在apps.ai_service。程序不得导入旧fishery_ai或运行时依赖Prototype路径。

## 2. HTTP v1 批次 DTO

`POST /api/ingestion/batches`，Content-Type application/json。示例是虚构窗口，不包含令牌：

```json
{
  "schema_version": 1,
  "batch_id": "example-batch-1",
  "session_id": "example-session",
  "sequence": 0,
  "device_id": "sim-pond-1",
  "timestamp": "2026-10-14T00:00:10+00:00",
  "window": {
    "start": "2026-10-14T00:00:00+00:00",
    "end": "2026-10-14T00:00:10+00:00",
    "duration_s": 10
  },
  "water": {
    "aggregation": "window_mean",
    "sample_count": 10,
    "metrics": {
      "temperature_c": {"unit":"°C","mean":26.4,"min":26.3,"max":26.5,"latest":26.4,"valid_samples":10,"invalid_samples":0},
      "ph": {"unit":"","mean":7.5,"min":7.4,"max":7.6,"latest":7.5,"valid_samples":10,"invalid_samples":0},
      "dissolved_oxygen_mg_l": {"unit":"mg/L","mean":6.4,"min":6.3,"max":6.5,"latest":6.4,"valid_samples":10,"invalid_samples":0}
    }
  },
  "visual": {
    "aggregation": "window_summary",
    "frames_processed": 20,
    "valid_frames": 20,
    "anomaly_counts": {"suspected_lesion":0,"surface_anomaly":0,"suspected_dead":0},
    "behavior_ratios": {"normal_activity":0.8,"reduced_activity":0.1,"feeding":0.1,"feeding_anomaly":0,"unknown":0},
    "length": {"average_length_cm":null,"length_sample_count":0,"valid_frame_count":0,"calibration":"uncalibrated","calibration_id":null},
    "visible_fish_count": 8.5,
    "model_version": "synthetic-visual-v2"
  }
}
```

固定结构拒绝未知/重复 JSON 字段，拒绝 NaN/Infinity、bool 代替数值、非法类型/单位/范围。ID 限制为 1–64 个 ASCII 字母数字、下划线或连字符，device_id 须在服务器 allowlist；默认只有 sim-pond-1。

时间必须带时区并归一化 UTC；timestamp = window.end。窗口 1–60 秒，duration 与起止一致；未来时间或超过 300 秒延迟拒绝。水质物理范围复核温度 -50–100°C、pH 0–14、DO 0–100 mg/L；这不是水质风险阈值。

R2B-2 时间修正：monotonic 到点不保证 UTC 窗口已经结束，旧发送逻辑可在提前唤醒/两种时钟偏差时发送未来窗口。生产端现在发送前确认 UTC 已到 window.end；最多 1 秒等待预算 / 3 次检查，仍未完成或明显时钟偏差则 SIMULATOR_CLOCK_OUT_OF_SYNC 并关闭 Reporter。窗口时间不重写，服务端未来/超过 300 秒拒绝保持不变。联调已去掉一秒人为缓冲；确定性测试复现默认 10 秒周期的 UTC 提前 5ms 情况，并验证修复。两个进程/真实设备的时钟同步、系统大幅跳时仍属部署限制，不无限容忍未来数据。

water 或 visual 可以为 null，但不能同时为空。两个通道独立更新；缺失通道不复制另一通道，也不清掉其末次记录。接收时间由服务器生成，客户端不能指定 source、quality、freshness、received_at 或真实设备标识。

## 3. 窗口与业务语义

- 窗口定义为 (start, end]，默认 10 秒。水质逻辑采样默认每 1 秒，视觉逻辑帧默认每 0.5 秒；与上报周期独立，周期须整除窗口。本模拟器在推进窗口时生成逻辑样本，不执行真实采集或视频推理。
- 温度、pH、DO 的 water.mean 是各指标**窗口内有效样本的算术平均**，输出保留三位小数，不是单次值。每个样本按其采样时的通道状态、缺失/无效标记与物理范围过滤，不使用窗口结束状态代替整窗质量。min/max/latest 同样只包含有效样本；valid_samples + invalid_samples ≤ sample_count，差值为缺失样本。有效数为零时四个值都必须 null。
- R2B-1：原始窗口均值和样本证据仍完整保存。每指标质量分 valid / partial（有效覆盖不完整）/ invalid / missing。Reader 只投影完整有效指标，其他指标为 None；任一 invalid 样本或无可用指标使 canonical Reading 为 INVALID，部分可用为 PARTIAL。独立 analysis.data_quality 保留原始质量与覆盖，避免把总体 INVALID 误解为所有指标都不可判断。
- 完全未收到 water 是 NO_DATA；已有全缺失/无效窗口仍是一个存在但不可用的 Snapshot。STALE 和连接 OFFLINE 是独立时间维度，不能改成正常。
- 视觉 frames_processed 是窗口内尝试的帧数，valid_frames 是有效帧数，无效帧不参与统计。anomaly_counts 是每类信号出现的有效帧数，类别可重叠；全零只表示有效帧未出现所列信号，不证明健康。疑似病灶、体表异常、疑似死亡均为检测信号，非最终疾病诊断。
- behavior_ratios 是互斥行为的有效帧比例，总和为 1；没有有效帧时均为 0，页面显示“无有效帧”，不能解释为正常活动。无有效视觉帧不使已有异常事件自动消退。
- **画面平均可见数** = 有效帧可见鱼数之和 / valid_frames；零鱼帧计入，无效帧排除。valid_frames 为 0 时 visible_fish_count 为 null，不是 0；不是累计鱼数或鱼池存量。
- **窗口平均体长** = Σ(帧平均体长 × 该帧有效体长测量数) / Σ(有效体长测量数)，等价于所有有效体长检测记录的算术平均，保留三位小数。两帧分别 2 条有效测量、均值 10 cm 和 6 条、均值 20 cm，结果 17.5 cm。length_sample_count 是有效体长检测记录总数，valid_frame_count 是有有效体长测量的帧数；测量数不一定等于可见鱼数，零鱼帧无体长测量。重复检测记录不代表独立鱼个体，更不代表全池平均体长。
- 默认未标定：体长 null、测量数/体长有效帧数为 0。手写 Phase 可启用纯 simulated 标定，同时提供模拟 calibration_id；逐帧检查标定状态，不宣称真实厘米精度。
- 上述帧数为 v1 的受限可选统计字段，旧 v1 批次仍可接收，已有 SQLite 不迁移、不回算旧窗口。新生产端 model_version 为 synthetic-visual-v2；旧体长计数曾表示帧数，页面明确标为旧语义，不冒充新的测量计数。新增字段仍严格校验，拒绝额外未知字段和相互矛盾的统计。
- model_version 保留模型来源位置，当前只有 synthetic 生产端。未来 boxes、track IDs、受控媒体引用须增加受限合同/版本，不使用任意扩展字典或本地路径；R2A 未生成截图、录像或检测框。



## 4. 存储、时间和生命周期

业务路径由ManagementPaths装配，Monitoring Schema v2。每操作短连接、事务提交/关闭；显式实例缺库或旧Schema拒绝，不自动建库/迁移/回退。新空实例必须明确初始化。

默认每设备每通道360个历史窗口、每设备1440批次、全局300事件。活动及ACK/人工结束审计关联受保护，不能用裁剪绕过手动删除保护；文件不保证立即缩小。

- 相同batch或device/session/sequence的相同有效内容幂等；内容冲突409。有效重复/乱序可更新接触时间，但不重写原观测、重建事件。
- 乱序窗口保留历史，只有更新的当前观测推进current与事件；相同观测时间歧义拒绝。新Session不证明恢复。
- 批次失败不写任一通道/事件；成功状态在一个事务提交。完全缺少的通道不覆盖另一通道。
- 默认观测超过30秒为stale；最后有效通道接触超过90秒为offline，未接收为never_received。各通道独立，在线不代表新鲜。
- query不重新采样；读时过期只撤回当前确定性，不修改历史时间或写入新恢复事件。

规则HIT、CLEAR、INSUFFICIENT_EVIDENCE、NOT_EVALUATED分开；非HIT没有异常严重等级。水质阈值只在diagnosis中，rules负责质量/时效证据门禁，不复制阈值。旧读数、缺测或另一等级出现不能自动证明恢复。

风险周期、三窗视觉恢复、ACK、人工结束及删除的完整当前合同见 [事件管理](../deep-dive/EVENT_MANAGEMENT.md)，不在本页另存一份状态机。

## 5. 统一读取和AI来源

当前水质Tool的设备由服务端绑定，模型参数仅{}，不得从正文选择实例/路径/设备。返回有限值、来源、观测/接收/评估时间、质量、新鲜度、连接和规则；Source Gate核对本轮Receipt，历史聊天不产生新来源。

Knowledge只返回启用文本的有限Evidence，和现场事实分开。评分是可选独立合同，见 [评分规则](../deep-dive/EXPERIMENTAL_WATER_SCORE.md)。Web默认Knowledge要求不因Monitoring-only QQ而取消。

Normal/Streaming共享原ToolCallingService；停止、超时、资源关闭和Commit条件不因渠道而跳过。QQ General无Tool路径不伪造Monitoring Receipt；Water实际调用本轮工具。QQ预算与发布合同见 [QQ Bot](../deep-dive/QQ_BOT.md)，Web工具/Prompt扩展见 [开发指南](../deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。

## 6. 历史统计合同

### 服务入口与统计边界

R2D-1B 提供 Monitoring 只读服务，没有新增 HTTP API。R2D-1C 的历史 Tool 仅为离线候选，见下节；正式网页仍未开放。设计依据见 [R2D-1A](../deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)。

```python
result = monitoring.query_water_history(
    device_id,
    lookback_minutes=30,
    metrics=["dissolved_oxygen_mg_l", "temperature_c"],
)
```

- `lookback_minutes` 只接受真正的 int：10 / 30 / 60；不接受 bool、float、字符串或自动转换。metrics 接受 1–3 个不重复的已知指标组成的 list/tuple，省略时为三项，输出按固定指标顺序；不接受 null、空列表或字符串。device 必须来自 Monitoring 已登记设备。
- Service 只取得一次时钟并归一化 UTC，范围为 `(evaluated_at-lookback, evaluated_at]`。Repository 使用参数化 SQL、既有时间索引及一次读事务，按 window.end 读取最多 721 条；超过 720 条明确拒绝，不缩短范围、不分页或自动重试。没有改动 SQLite schema / 保留配置或既有 `history()`。
- `history.py` 是纯计算入口，复用上报的窗口/指标 Schema 校验及 `water_metric_facts()`；校验参照原 received_at，而非把旧观测按现在的新鲜度重评。不调用 DiagnosisService、EventService 或 Current 查询，不产生任何写入。查询时刻之后才接收的并发迟到记录不参与结果，数量另列。
- 完整处于请求区间的窗口才进入样本计数/数值统计；跨起点窗口只贡献其实际交集的 received coverage，不能按时间比例估算均值。边界排除数单列。候选及存储 JSON 损坏均安全拒绝，不把损坏混同于合法 invalid 数据。

返回独立、脱离存储对象的 dict，`projection_version=management-water-history@1`：

| 字段 | 当前合同 |
|---|---|
| status / query_completed | NO_DATA：没有完整匹配窗口；PARTIAL：有匹配窗口但可靠覆盖、Session 或歧义存在限制；OK：请求区间的全部所选指标可靠覆盖完整、无歧义/未知 Session/Session 切换。合法返回的 query_completed 均为 true |
| requested_range / evaluated_at | UTC 起止、`(start,end]` 和固定查询时刻；不是新采样时间 |
| source_kind / aggregation | simulator / window_mean；历史未重新标为当前事实 |
| counts | 候选、完整匹配、跨界排除、查询时刻后接收、歧义、重复观测时刻组/行、未知 Session 数。重复行数是歧义组中全部行数，不只是多出的行数 |
| metrics | 每指标 valid / partial / invalid / missing 窗口数；声明的 valid/invalid/missing/总样本数；可靠窗口/有效样本数、首末窗口均值与差值、窗口均值极值及独立时间/批次引用。并列极值返回次数、首次与末次引用 |
| coverage / metrics.*.reliable_window_s | received coverage 是候选窗口交集的区间并集；可靠覆盖仅由完整、非歧义且指标 valid 的窗口构成。分别返回秒数/比例，不用条数乘 10 秒，也不是样本覆盖率 |
| gaps / metrics.*.gaps | 全局缺口为 NO_RETAINED_WINDOW；逐指标缺口为 NO_RELIABLE_METRIC（也包括全局缺口、跨界或歧义排除）。各自给出全量 count/total_s，最多 12 段及 omitted_count；不能相加当作不同缺口 |
| sessions / continuity | 已知 Session 数、相邻观测记录的已知 Session 变化及省略数；连续段仅包含全部所选指标可靠、已知同 Session、窗口精确衔接的记录。unknown / 歧义 / 不可靠记录、时间缺口和 Session 切换截断连续段，最多展示 12 段；不推导异常持续时长 |
| details / details_omitted | 最多 12 个等长时间桶各选末个实际窗口；是抽选，不是桶平均或完整轨迹。全量统计先于抽选；极值引用不依赖抽选结果。partial / invalid / missing 或歧义明细的 window_mean 为 null |
| latest_observation_lag_s | 查询终点减候选中的最大观测时间；没有候选为 null。不是当前 freshness 或设备连接状态 |
| retention_completeness / limitations | 因无裁剪水位，始终 UNKNOWN；保留 NOT_CURRENT_OBSERVATION 和 RETENTION_COMPLETENESS_UNKNOWN。若区间已被可靠记录完整覆盖，UNKNOWN 本身不阻止 OK，不声称区间之外留存完整 |
| analysis | persistent_low_oxygen / recovery 均 NOT_EVALUATED；没有历史规则重评、回归趋势、预测或新阈值 |

质量只按实际指标判断：partial / invalid / missing 不进入可靠数值统计；其他完整有效指标仍可用。所有样本数是匹配记录中的声明总数，歧义记录可能重复计数，不代表独立物理样本；`reliable_valid_samples` 单列排除歧义及不可靠指标后的计数。缺失值不补零，历史“最低值”专指最低有效**窗口均值**，不声称知道原始最低采样的确切时间。

同时间或传递性重叠窗口整组标为歧义，排除可靠数值统计和可靠覆盖；received coverage 仍取并集，不重复累加。已知不同 Session 可参与分段的历史极值，但不能连接成持续状态。旧批次表被裁剪后 Session 保持 unknown，不猜回来源。没有留存记录不等于设备离线，也不能区分“从未上报”和“被裁剪”；NO_DATA / PARTIAL 都不证明环境正常或恢复。

静态限额：720 条候选 / 单行 JSON 8 KiB / 明细 12 条 / 每组缺口与连续段 12 条 / 完整紧凑 UTF-8 JSON 24 KiB。超过输出上限拒绝整个结果，不裁断 JSON。SQLite 保持既有锁、短连接及 5 秒连接等待；本阶段不接入 AI Turn，后续 Handler 必须遵守原有 Stop / Deadline，不能据此宣称 SQL 已支持强制中断。

安全拒绝使用 `HistoryQueryError.code`：`INVALID_WATER_HISTORY_QUERY`、`INVALID_HISTORY_QUERY_TIME`、`HISTORY_QUERY_BUDGET_EXCEEDED`、`HISTORY_RECORD_INVALID`、`HISTORY_RECORD_TOO_LARGE`、`HISTORY_RESULT_TOO_LARGE`、`HISTORY_STORAGE_ERROR`；不附 SQL、路径或记录内容。未知设备保持既有 `UNKNOWN_MONITORING_DEVICE` 行为。

与设计的细化：边界窗口的时间交集只计实际 received coverage；retention UNKNOWN 与区间 OK 分开；增加单行 8 KiB 防护和 as-of 接收时间过滤。Monitoring 不负责 Receipt、Policy 或发布配置；这些边界见下节。

离线验证入口：`python -m unittest discover -s apps/monitoring/tests -v`，其中 `test_water_history.py` 使用临时 SQLite 与固定时钟；不读取运行数据库或调用 Provider。


## 7. 传输与真实替换

开发上报接口只在显式enable-ingestion、本机Host/Origin/地址与一次性Token有效时启用，Simulator不直接写Repository。客户端不能声明自己是正式传感器。真实生产端需独立身份、质量、时钟、视频与规则证据合同，不能把sample.mp4当现场采样。

简略格式见 [设备接口](../DEVICE_INTERFACE_QUICK.md)，未来设计见 [真实设备规划](../deep-dive/plan/REAL_DEVICE_INTEGRATION.md)。本轮没有实施任何新硬件、写Tool或Schema。


## 独立设备报告接入（2026-11-04）

- `apps.device_reports` 选择性复用 Prototype 的 TEXT_PACKAGE_API v1接收机制；端点 `/api/fish/reports`，必须绑定设备ID和专用令牌，默认只监听回环，局域网须显式绑定私网IPv4。
- 独立 `device-reports.sqlite3` 为报告Schema v1；仅显式初始化、已有文件拒绝覆盖。不更改Monitoring v2、Settings、Policy、规则和事件生命周期。Web使用mode=ro/query_only读取最近20条。
- 确认持久提交后才返回accepted；重复ID相同内容duplicate，不同内容409；最多5000条，不自动清理。写入失败不假报成功。
- 四个cmd增加运行模式菜单；`full`保持原行为，`water-only`停止模拟视觉且服务器拒绝混入模拟视觉。绑定报告须显式指定目录和设备；不自动启动LAN监听或改防火墙。
- 设备原文用纯文本渲染，报告新鲜度阈值120秒，只说明报告时效；不声称连续在线、疾病确诊、可靠恢复或真实视频已接入。
- 发行白名单新增接收模块和启动辅助文件；不依赖Prototype路径。QQ运行准备记录只刷新Web启动文件的实现摘要及总Scope摘要，candidate/qualification/权限/预算不变，旧本机request需维护者重新核对，新运行仍需人工批准。
- 回退代码前正常停止接收器和本次Web/Simulator。专用报告库保留；关闭接收器、使用full模式即可停止设备联调，不需要修改或回滚Monitoring数据。未执行真实硬件、QQ或模型联网验收。


验证记录：设备/模式专项13项通过；本机独立HTTP进程合成报告accepted→duplicate、仅1条入库并回收接收进程；Node全量130项通过。Python全量804项：802通过，2项启动测试失败（参数连续顺序断言、一次模拟器启动等待超时）；调整cmd参数顺序后，两项与模式专项合计6项复测全部通过，未再次重跑整套804项。此前旧QQ指纹拒绝已通过只更新candidate准备摘要修复；一个撤权测试5秒启动等待曾超时，单独复测及最终全量中的该用例均通过。慢机器启动/异步测试仍存在时间敏感性，未放宽等待或删除断言。

打包白名单/隔离导入与演示启动专项10项通过，PowerShell启动文件及7个文档命令块解析通过，199个本地文档链接有效，pip check和git diff --check通过。日志保留于本次工作区忽略目录 `outputs/device-*.log`；没有修改真实数据库或已有QQ请求/批准，没有连接硬件、QQ或Qwen。正式硬件验收尚未执行。
