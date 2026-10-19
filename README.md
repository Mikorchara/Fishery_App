# Fishery Management

独立的本机智慧渔业管理应用。Python 3.11+ / Flask / SQLite / 原生 JavaScript；无需 npm 构建。程序采用 `apps.*` 包，不安装或导入旧 `fishery_ai`。初始代码来源为已提交的 MIG-2（`2b099cf`），本仓库从干净 Git 基线开始。

## 安装与测试

在本项目目录建立自己的环境（不能复用旧项目的 .venv）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'setuptools>=68' -e .
.\.venv\Scripts\python.exe -I scripts/dev/run_management_tests.py
```

测试只用 Fake Provider 和固定夹具；真实连接必须由用户单独批准。启动不请求模型。

## 隔离演示实例

MIG-3 **没有迁移真实业务数据或密钥**。先初始化一个新的、位于本项目 outputs 下的空白测试实例；不能用初始化代替真实数据迁移：

```powershell
.\.venv\Scripts\python.exe -I -m apps.management_web --project-root "$PWD" --data-root "$PWD\outputs\acceptance-instance" --init-data
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\acceptance-instance" -NoAssistant
```

访问 http://127.0.0.1:8766 ，Ctrl+C 回收本次服务器与模拟器。实例已有则不要重复初始化。初始化知识库为空，不会自动导入旧知识；固定测试夹具只用于自动测试。`-NoAssistant` 保证演示不会读取真实密钥或发起模型请求。

若旧服务占用8766，增加 `-Port 18766`（本轮实际验收端口）或其他空闲端口；不要终止未知进程。

正式数据根将使用 `%LOCALAPPDATA%\FisheryManagement`，本轮未访问/初始化该实例。完成独立批准的数据迁移后才能使用 `-UserData`。不要省略数据根参数去使用历史兼容路径。

## 开发入口

- [启动、数据与打包](apps/docs/BUILD_RUN.md)
- [结构与集成](apps/docs/STRUCTURE.md)
- [业务与 Backend 开发指南](apps/docs/deep-dive/AI_BACKEND_DEVELOPMENT_GUIDE.md)
- [MIG-3 迁移与验收](apps/docs/deep-dive/MIG3_STANDALONE.md)
- [工程规则](AGENTS.md)

Scope、Prompt、Tool 定义及已批准本地试用边界保持来源版本；迁移成功不构成新的真实 Provider 资格。Credentials 仍是独立用户私有存储，项目根变化会选择新的项目身份，不自动复制/沿用旧密钥。
