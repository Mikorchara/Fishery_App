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

新电脑安装依赖后，先执行一次 `.\scripts\dev\Initialize-Management.ps1`，自动创建唯一日常实例和31条初始背景资料，再用上面的入口。两终端不需要QQ配置或模型密钥；三终端另需给同一实例配置QQ，不会重建数据库。全部数据统一在 `outputs/qq-m3-real-test`，不要复制别人的outputs和密钥。

- 当前观测和视觉统计为SIMULATOR；本地视频只是录像，不进行NPU推理，不冒充真实采样。
- QQ为独立进程，只有当前水质只读Tool；默认不联网，不具有事件确认、删除或设备控制权限。
- QQ正在调整为持续会话、网页Token设置和Web式自然回答；**这些调整尚未实现，当前代码仍为旧有界模式**。尚未配置QQ的用户可先使用两终端，待新模式验收后再一次配置；当前行为与设计见[QQ专题](apps/docs/deep-dive/QQ_BOT.md)。
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
