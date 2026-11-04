# 设备怎么把数据发给 Management

**现在支持两条独立的数据通道。** 开发板报告可以接收并在网页查看；真实水质传感器和实时视频仍需单独对接。

| 数据 | 发送到哪里 | 网页用途 |
|---|---|---|
| 原 Simulator 的水质/视觉统计 | 本机 `8766/api/ingestion/batches` | Monitoring、水质历史、规则事件和已授权 AI 查询 |
| 开发板 TEXT_PACKAGE_API v1 检测报告 | 独立接收器 `8780/api/fish/reports` | 视频页右侧“设备视觉报告”，独立保存原报文 |
| 根目录 `sample.mp4` | 启动时通过 `-DemoVideo` 指定 | 仅本地录像播放，与上述两路数据独立 |

开发板报文目前**没有水温、pH、溶解氧**。设备联调时，这三项仍由 Simulator 模拟并标注 SIMULATOR；开发板报告不会伪装成模拟视觉，不自动生成 Monitoring 事件、恢复证据、QQ事件提醒或 AI 查询来源。报告设备也不自动加入首页 Monitoring 设备计数。

## 1. 先准备电脑

电脑和开发板连接同一可信局域网。在 **Management 根目录**打开 PowerShell，先完成根目录 [开始使用](../../开始使用.md) 的环境安装和 `outputs/local-demo` 初始化。

另建报告存储（只执行一次，不覆盖已有文件）：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -InitStore
```

看到 `DEVICE_REPORT_STORE_CREATED` 即完成。默认文件是 `outputs/device-reports/device-reports.sqlite3`，与原 Monitoring 库分开。如果提示已存在，跳过初始化，不删除重建。

仅检查参数（不打开数据库、不读令牌、不联网）：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Check
```

## 2. 启动网页，只模拟水质

先正常关闭旧 Web / Simulator，再执行：

```powershell
.\scripts\dev\run_local.ps1 -DataRoot "$PWD\outputs\local-demo" -NoAssistant -ShowTerminals -InteractiveScenario -OpenBrowser -SimulationMode water-only -DeviceReportDirectory "$PWD\outputs\device-reports" -DeviceReportDeviceId fish-monitor-orin-01
```

在 Simulator 中选水质场景，推荐先选 `1` 正常。此模式不会生成模拟视觉；“疑似疾病、摄食减少”等视觉参数不生效。水质异常规则仍正常运行。

要同时播放录像，在上述命令末尾加 `-DemoVideo "$PWD\sample.mp4"`。打开 http://127.0.0.1:8766 的“视频监控”：左侧模拟水质、中央录像、右侧设备报告。

`fish-monitor-orin-01` 是示例设备 ID，必须与开发板 `device_id` 一致；修改时也要修改下一步接收器的 `-DeviceId`。

## 3. 单独启动报文接收器

另开 PowerShell，进入同一项目。用 `ipconfig` 找到电脑当前局域网 IPv4（换网络后可能变化），将下面占位符替换为实际地址：

```powershell
.\scripts\dev\Start-DeviceReports.ps1 -Serve -Bind '<电脑局域网IPv4>' -DeviceId fish-monitor-orin-01
```

按提示输入与组员约定的 **32～128位字母数字令牌**，输入不回显。不要把令牌放到源码、Git、截图或普通日志中。看到 `DEVICE_REPORT_LISTENING`，保持这个窗口运行。

- 默认端口8780；Web仍是8766，互不占用。
- 不填 `-Bind` 时只监听127.0.0.1，开发板访问不到。
- 只绑定具体的私网IPv4，不使用0.0.0.0。防火墙如需放行，仅限可信专用网络、开发板地址与此端口；程序不自动改防火墙。
- 首版是局域网 HTTP，不含 TLS，不要直接暴露到公网。

## 4. 组员在开发板上填写

```http
POST http://<电脑局域网IPv4>:8780/api/fish/reports
Content-Type: application/json
X-Device-Token: <私下约定的令牌>
```

正文按原 [TEXT_PACKAGE_API.md](development/TEXT_PACKAGE_API.md) 的 v1 JSON 发送。保留 `schema_version`、`report_id`、`device_id`、`sent_at`、`window`、`has_abnormality`、`report_text`、`detection`、`abnormalities`、`behavior`、`measurement`。本端不要求添加水质字段。

- 时间带时区，使用实际采集时间，电脑与开发板先校时；不得发送未来时间。
- 同一报文重传保留 ID 和内容；新报文换 ID。同 ID 不同内容会拒绝。
- `behavior`、`measurement` 未运行时保留 `null`，不能填“正常”。
- JSON最大16 KiB，窗口最长1小时，最多60次请求/分钟。建议正常和异常窗口都上报；仅异常上报时，沉默不能证明恢复。
- 原文示例的窗口起止和 `duration_s` 可能不一致，实际发送应校正；接收器保留原证据并返回警告，不替设备改时间。

返回 `accepted` 表示已提交到独立报告库；`duplicate` 表示相同报文已保存。403检查令牌/设备ID，409检查重复ID内容，413检查大小，429降低频率，503检查存储状态。不要遇错就无限重试。

## 5. 验收和停止

1. 发一条真实报告，检查开发板收到 `accepted`。
2. 网页右侧应出现相同设备、观测时间、报告正文与统计；未接入显示未知，不显示“全部正常”。
3. 相同报文重传应返回 `duplicate`，页面不增加重复记录。
4. 超过120秒的观测标为过期；这是报告时效，不是设备在线或疾病恢复判定。
5. 接收器窗口按 Ctrl+C 停止；Web/Simulator按原方式停止，存储保留。

页面最多显示最近20条，独立库上限5000条，满后明确拒绝新报文，不自动删除历史。达到上限请停接收后由维护者备份并安排新存储，不清空旧库。

当前已完成合成报文离线验证；组员仍需确认真实开发板的网络、令牌、时间和实际字段。**视频流与设备报告是两项验收，不能互相替代。**

原模拟批次的精确格式见 [监测协议](development/INTEGRATION.md)；四个日常入口见 [启动说明](BUILD_RUN.md)。
