# 数据接入说明（简略版）

本页只介绍**现在已经使用的模拟数据格式与传输方式**，方便组员讲解或编写采集端。详细报告保留不变。

## 1. 怎么传

**模拟器 → HTTP POST 发送 JSON → Management 校验、存储 → Web 和 QQ 查询。**

默认每10秒发送一个已完成的观测窗口，包含水质与视觉统计。采集端不直接写数据库，也不负责判断事件是否发生或消退。

```http
POST http://127.0.0.1:8766/api/ingestion/batches
Content-Type: application/json
X-Simulator-Token: <由启动器提供的本次令牌>
```

当前接口只允许本机上报，启动器会开启接收并提供令牌。外部设备不能直接通过局域网访问此接口；真实设备采集和真实来源认证尚需另外适配，不能把真实数据改名为模拟数据后当作已完成接入。

## 2. 发送什么

下面是**完整、虚构的格式样例**。时间只用于说明，运行时必须填写真实观测窗口，不能直接照抄旧时间。

```json
{
  "schema_version": 1,
  "batch_id": "example-batch-0001",
  "session_id": "example-session-0001",
  "sequence": 0,
  "device_id": "sim-pond-1",
  "timestamp": "2026-10-29T08:00:10Z",
  "window": {
    "start": "2026-10-29T08:00:00Z",
    "end": "2026-10-29T08:00:10Z",
    "duration_s": 10
  },
  "water": {
    "aggregation": "window_mean",
    "sample_count": 10,
    "metrics": {
      "temperature_c": {"unit": "°C", "mean": 26.5, "min": 26.5, "max": 26.5, "latest": 26.5, "valid_samples": 10, "invalid_samples": 0},
      "ph": {"unit": "", "mean": 7.4, "min": 7.4, "max": 7.4, "latest": 7.4, "valid_samples": 10, "invalid_samples": 0},
      "dissolved_oxygen_mg_l": {"unit": "mg/L", "mean": 6.2, "min": 6.2, "max": 6.2, "latest": 6.2, "valid_samples": 10, "invalid_samples": 0}
    }
  },
  "visual": {
    "aggregation": "window_summary",
    "frames_processed": 20,
    "valid_frames": 20,
    "anomaly_counts": {"suspected_lesion": 0, "surface_anomaly": 0, "suspected_dead": 0},
    "behavior_ratios": {"normal_activity": 1.0, "reduced_activity": 0.0, "feeding": 0.0, "feeding_anomaly": 0.0, "unknown": 0.0},
    "length": {"average_length_cm": null, "length_sample_count": 0, "valid_frame_count": 0, "calibration": "uncalibrated", "calibration_id": null},
    "visible_fish_count": 3.5,
    "model_version": "sim-example-v1"
  }
}
```

## 3. 主要字段是什么意思

| 字段 | 含义 |
|---|---|
| `batch_id` | 这一批数据的编号；同批重传不要换编号或改内容 |
| `session_id` / `sequence` | 本次采集会话与窗口序号；新会话换 ID，序号从0递增 |
| `device_id` | 服务端预先登记的设备编号 |
| `timestamp` / `window` | 观测结束时间和窗口起止，`timestamp` 必须等于 `end`；`Z` 表示 UTC |
| `water.metrics` | 水温、pH、溶解氧；单位分别为 `°C`、空字符串、`mg/L` |
| `mean/min/max/latest` | 窗口内均值、最小、最大、最后一个有效值 |
| `sample_count` / `valid_samples` / `invalid_samples` | 尝试采样、有效采样、无效采样次数；未取得读数可形成点数差额 |
| `frames_processed` / `valid_frames` | 参与窗口分析的帧数与有效帧数，不代表已经接入真实视频 |
| `anomaly_counts` | 有效帧中检出疑似病灶、水面异常、疑似死亡信号的次数，不是确诊鱼数 |
| `behavior_ratios` | 五种行为的窗口比例；有有效帧时合计为1 |
| `length` / `visible_fish_count` | 长度统计与窗口可见鱼数统计；未标定时不能输出真实厘米长度 |

只上报水质时，可以将 `visual` 整项设为 `null`；只上报视觉统计时，`water` 可以为 `null`，但两项不能同时为空。

## 4. 记住这几条要求

- 字段和单位按格式填写，不随意添加字段；JSON 不超过8 KiB。
- 时间带时区，窗口长度1～60秒；窗口结束不能晚于服务器当前时间，也不能早于接收时刻超过300秒。
- 无有效读数时，mean/min/max/latest 填 `null`、`valid_samples=0`，不要补0；三种指标字段仍需保留。
- 同一窗口真实采了几次就写几次，不能把旧缓存值重复算成新采样。有效与无效次数之和不超过尝试次数。
- 缺测、无有效帧和设备离线不能当作“正常”。

成功返回示例：

```json
{"status": "accepted", "updated_channels": ["water", "visual"]}
```

`duplicate` 表示已识别重复批次；`out_of_order` 表示没有更新当前值。错误返回 `error_code`，例如格式/时间错误400、未授权403、批次冲突409、报文过大413。

## 5. 视频只需要先分清一件事

**当前发送的是视觉统计 JSON，不是视频流。** Management 现在没有实际视频播放；不能把 RTSP 地址、图片或视频直接塞进上述报文。

以后接摄像头时，视频播放需要单独接入；若只讨论目前系统，报告中说“支持模拟视觉统计展示”即可。

日常运行见 [启动指南](BUILD_RUN.md)；精确字段校验见 [contracts.py](../monitoring/contracts.py)，HTTP 接收见 [app.py](../management_web/app.py)。需要真实设备和视频方案时，再看 [详细报告](deep-dive/plan/REAL_DEVICE_INTEGRATION.md)。
