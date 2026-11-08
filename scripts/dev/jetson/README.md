# Jetson 开发板联调

这里集中存放 Management 侧的 SSH 排查步骤和旧版报文精简工具。正式接收器及网页启动见 [设备连接步骤](../../../apps/docs/DEVICE_INTERFACE_QUICK.md)。2026-11-08 交接后的板端现用 `peak_frame_v1` 自动发送完整单包。现行字段见 [设备视觉页改版与数据清单](../../../apps/docs/development/DEVICE_REPORT_REDESIGN.md)。

源码副本、现场日志、报文样本、验证结果和队列备份保存在 Git 忽略的 `outputs/hardware-evidence` 与 `outputs/hardware-checks`。SSH 密码、密钥和实际凭据使用原有私有存储。

## 到现场先核对

在实验室网络上用自己的 SSH 用户名和当前板端 IP 登录。以下命令只查看板型、现有启动配置能否读取、报告服务状态和发送脚本版本。

```bash
ssh <开发板用户名>@<开发板IP>
```

在 SSH 窗口中执行。

```bash
tr -d '\0' </proc/device-tree/model
printf '\n'
cd ~/fish_cpp_agent_integration
python3 start_all.py --check
systemctl is-active fish-reporter.service
sha256sum website_publish.py
```

2026-11-06 的只读归档识别到 NVIDIA Jetson Orin NX，架构为 aarch64。此前跑通的是板端录像回放推理。现场运行版本、实时摄像头和新配置仍要逐项确认。

下表记录旧版现场归档的控制点，供追溯。

| 要调整的内容 | 已核对的控制点 |
|---|---|
| 发哪些字段 | Python `website_publish.py` 的 `make_packets` 与 `Publisher.prepare` |
| 多久产出一轮检测统计 | 汇总端归档配置的 `report_interval_seconds` 为 60。报告服务也有自己的窗口配置，先核对两边 |
| 积压多久发一个包 | 归档的 C++ 汇总端约每 1.5 秒调度发送器，Python 发送器另有 1.5 秒节流和失败退避。实际速度还受 HTTP、队列和运行时影响 |
| 体长与行为多久出结果 | `start_all.py` 分别调度体长和行为。任务执行耗时和采集时间各自记录 |

先缩小报文，再用现场数据测量窗口结束到完整接收的耗时。需要调频时分别测量窗口、队列和任务调度，每次只调整一项。改动 C++ 调度需核对源码和运行二进制对应关系。

## 旧版精简报文候选

候选仅适用于下列归档源码指纹，供旧版复核。一次性直发、旧队列切换记录及验证结果已归入本机忽略目录 `outputs/hardware-checks/archive-legacy-lab`。

- `compact_payload.py` 保留网页所需的检测、体长、行为、时间和质量字段。开启 `"website_compact_reports": true` 才尝试单包。超过 16 KiB 或遇到未覆盖的输入时使用原打包方式。首次入队时选择格式，已有队列字节和原始归档继续沿用原逻辑。
- `make_candidate.py` 校验 2026-11-06 归档的完整文件摘要和发送函数原文。默认只检查。源码不匹配就停下，按实际板端版本重新审阅。
- `verify_candidate.py` 使用本机留存的归档样本做离线对照。已有验证结果在 `outputs/hardware-checks/compact-v1-candidate`。完整板端候选脚本待核对源码后生成到同一目录。

在 Management 根目录的 PowerShell 执行。第一条依赖本机已有的归档样本。第二条需要现场取得的 `website_publish.py` 本地副本。

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B .\scripts\dev\jetson\verify_candidate.py
.\.venv\Scripts\python.exe -X utf8 -I -B .\scripts\dev\jetson\make_candidate.py --source '<板端源码本地副本>' --evidence .\outputs\hardware-evidence\evidence-20261106T113300Z-c813c773\board-evidence.json
```

看到 `SOURCE_MATCH_VERIFIED` 后，可在第二条末尾加 `--write-candidate`，生成 `outputs/hardware-checks/compact-v1-candidate/website_publish.compact-v1.py`。目标已存在时拒绝覆盖。

现场切换前保存原脚本和配置的独立备份，核对进程归属，再由操作者安排停止和重启。先用默认开关验收原流程，再开启精简，用新产生的报告对照接收、网页字段、队列积压和去重。需要回退时关闭开关或恢复原脚本与配置，保留现有队列和历史。

## 三窗消退建议

板端约 60 秒一窗，三个连续完整窗口约 3 分钟，从第一个无信号窗口的起点计，还要等第三份报告完整抵达。按同一设备、同一检测类别、独立观测窗口计数。每窗需要明确完成该类检测且无信号，分包和重发只算同一个窗口。缺窗、缺包、过期、检测任务未运行或再次命中时中断计数。现场确认板端正常窗口也会发送，并且能提供对应的检测覆盖证据后，再启用板端自动消退。当前真实设备事件仍沿用待核实规则。
