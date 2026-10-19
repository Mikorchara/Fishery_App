# Fishery Management

独立的本机智慧渔业管理应用。Python 3.11+ / Flask / SQLite / 原生 JavaScript；无需 npm 构建。程序采用 `apps.*` 包，不安装或导入旧 `fishery_ai`。包含统一监测与历史、模拟器、AI 助手、事件、知识内容管理和系统设置；真实传感器、视频和 NPU 尚未接入。

**使用入口：[中文使用与学习指南](apps/docs/USER_GUIDE.md)**。MIG-1～MIG-5 主要迁移与人工验收已完成（凭据及网页验收状态由用户确认）；Qwen Normal / Streaming 三工具仍是本地实验，不是生产 `released`。

## 安装与测试

在本项目目录建立自己的环境（不能复用旧项目的 .venv）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'setuptools>=68' -e .
.\.venv\Scripts\python.exe -I scripts/dev/run_management_tests.py
```

测试只用 Fake Provider 和固定夹具；真实连接由用户主动操作。启动不请求模型。完整管理测试还需要 Node。

## 日常启动：正式数据，只启动 Web

在 `D:\CodexProject\Fishery_Management` 执行：

```powershell
.\.venv\Scripts\python.exe -I -B -m apps.management_web --project-root "$PWD" --user-data --enable-assistant --assistant-multi-round-trial --assistant-streaming-trial --assistant-history-trial --assistant-tools-trial
```

访问 http://127.0.0.1:8766 ，Ctrl+C 停止。此命令打开已迁移的 `%LOCALAPPDATA%\FisheryManagement`，不启动 Simulator 或数据上报接口。AI 工具仍须用户授权，密钥须可用；页面发送或主动测试连接才可能请求模型。已有库缺失时停止核对，不初始化空库掩盖遗漏。

## 开发联调：隔离实例 + Simulator

先按 [使用指南](apps/docs/USER_GUIDE.md) 一次性初始化新的 `outputs\dev-instance`，以后可一行启动：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\dev-instance"
```

**启动器始终运行 Simulator 并写入所选实例**，即使加 `-NoAssistant` 也如此；不要无意使用 `-UserData` 向正式监测库写模拟数据。端口冲突会拒绝启动；可用 `-Port 8767`（Web CLI 用 `--port 8767`）另选端口，不结束未知进程。

## 开发入口

- [启动、数据与打包](apps/docs/BUILD_RUN.md)
- [用户使用与学习指南](apps/docs/USER_GUIDE.md)
- [结构与集成](apps/docs/STRUCTURE.md)
- [业务与 Backend 开发指南](apps/docs/deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)
- [MIG-3 迁移与验收](apps/docs/deep-dive/MIG3_STANDALONE.md)
- [工程规则](AGENTS.md)

Scope、Prompt、Tool 定义及已批准本地试用边界保持原合同；迁移成功不构成新的真实 Provider 资格。Credentials 是独立用户私有存储，路径与项目根身份有关，不放在业务数据根或 Git 中。迁移文档记录当时结果，当前操作以使用指南与 BUILD_RUN 为准。
