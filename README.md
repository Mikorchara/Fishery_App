# Fishery Management

独立的本机智慧渔业管理应用：统一水质与事件、Web AI、知识库、Simulator、本地录像，以及独立QQ Hybrid Bot。Python 3.11+ / Flask / SQLite / 原生JavaScript，无需npm构建，不依赖Prototype安装。

**第一次下载源码，只需先读 [开始使用](开始使用.md)，按步骤安装、启动和配置。** 已配置的机器看 [日常启动](apps/docs/BUILD_RUN.md)，全部文档从 [docs目录](apps/docs/README.md) 进入。

```powershell
# 两终端：Simulator + Web
.\scripts\dev\启动演示系统.cmd
# 三终端：Simulator + Web + QQ Hybrid（需本机配置及人工审批）
.\scripts\dev\启动QQ演示系统.cmd
# 带根目录 sample.mp4 的两个版本
.\scripts\dev\启动视频演示系统.cmd
.\scripts\dev\启动QQ视频演示系统.cmd
```

新电脑安装依赖后，先执行一次 `.\scripts\dev\Initialize-Management.ps1`，自动创建唯一日常实例和31条初始背景资料，再用上面的入口。两终端可直接运行，三终端需为同一实例配置 QQ。日常实例在 `outputs/qq-m3-real-test`，原始设备报告单独存入 `outputs/device-reports`。完整目录见[部署说明](apps/docs/guides/DEPLOYMENT.md)。

- 启动时选 `1` 使用完整模拟。选 `2` 时水质继续模拟，视觉统计来自通过 8780 接收的开发板报告。视频入口播放独立的本地录像。见[设备连接步骤](apps/docs/DEVICE_INTERFACE_QUICK.md)。
- QQ为独立进程；网页新配置可复用当前/历史水质、项目知识与实验评分四个只读Tool，旧模式兼容；默认不联网，不具有事件确认、删除或设备控制权限。
- QQ可在“系统设置 → QQ机器人”配置，采用持续运行与Web式自然回答；每次模型请求输出Token可调，启动仍需人工批准费用和访问范围。旧有界配置兼容，机制见[QQ专题](apps/docs/deep-dive/QQ_BOT.md)。
- 两/三终端及带视频版本共用一份日常实例；旧正式/演示目录保留，不自动合并。源码、业务数据和私有凭据分开。
- sample.mp4可作为获准源码演示素材跟踪；Wheel不包含视频、配置、数据库、密钥、报告或批准。交接不要打包整份outputs或.venv。

安装和离线回归：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'setuptools>=68' -e '.[qq]'
.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/run_management_tests.py
```

安装可访问包索引；自动回归只用Fake和合成数据，不连接QQ/Qwen。真实模型、QQ群与数据披露必须由操作者另行明确批准。

[网页使用](apps/docs/guides/USER_GUIDE.md) · [技术路线](apps/docs/presentations/TECHNICAL_ROUTE_TEAM.md) · [维护与回滚](apps/docs/deep-dive/OPERATIONS.md) · [工程规则](AGENTS.md)
