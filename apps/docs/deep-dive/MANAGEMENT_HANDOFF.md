# 组员首次配置（Windows）

已配置的原机器直接使用 [启动指南](../BUILD_RUN.md)。本页只在首次换电脑、换 Windows 用户或项目移动路径时执行；不修改旧实例以冒充新机器配置。

## 1. 准备环境

在自己的 Fishery_Management 根目录打开 PowerShell，使用 Python 3.11+ 和 Node。不要复制别人的 `.venv` 当作本机环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[qq]'
```

安装依赖访问包索引，不调用 QQ/Qwen。不需要 npm 构建。移交时提供源码、固定资源、脚本和文档；不要随手打包私有凭据、真实数据库、历史聊天/Trace、批准文件、used 标记或运行账本。群/成员 OpenID 也不要放进公开报告。

## 2. 创建本机 QQ 隔离配置

先确认 `outputs/qq-m3-real-test`、`outputs/qq-m3-real-config` **都不存在**。若已有目录，停止核对；不要删除、覆盖或重复初始化。需要保留旧实例时使用另外一组新路径，并在启动命令中明确指定。

在本机终端填入经负责人批准的 AppID、测试群/成员 OpenID（不是 AppSecret；不要在聊天中粘贴）。下面命令以本机 `$PWD` 生成绝对引用，建立空 Knowledge、Monitoring v2 和明确标记的合成数据，不导入任何人的正式库：

```powershell
New-Item -ItemType Directory -Path .\outputs -Force | Out-Null
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli prepare-demo --data-root "$PWD\outputs\qq-m3-real-test" --config-directory "$PWD\outputs\qq-m3-real-config" --app-id '批准的AppID' --group-id '批准的群OpenID' --member '批准的成员OpenID' --enable-ai
```

不要直接执行占位符。群与成员必须已在 QQ 平台取得相应测试资格；初始化配置不等于平台授权。

## 3. 本机设置密钥、检查和运行

QQ AppSecret 只在隐藏输入处亲自录入：

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli save-secret
```

DashScope Key 使用 Management 私有存储，通过原 Web「系统设置」按既有流程配置；见 [用户指南](../USER_GUIDE.md)。没有正式库的新电脑可先用第4节的无 Bot 隔离演示命令，省略 `-NoAssistant` 以装配 Web AI 并进入设置；保存新 Key 前的连接测试会真实调用模型，须由操作者主动同意。项目路径变化会改变私有存储身份；不要复制 `.env`、把 Key 写入 JSON/命令行，或从旧项目取回密钥。

```powershell
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check
```

Check 通过后，按 [启动指南](../BUILD_RUN.md) 运行 `启动QQ演示系统.cmd`，在 Simulator 窗口选场景，在 Bot 窗口人工批准本次有限运行。初始化和 Check 本身不联网，也不证明凭据有效；运行需负责人另行批准。

## 4. 没有正式知识库，只演示 Web + 模拟器

原 `启动演示系统.cmd` 首次要复制当前 Windows 用户的正式知识库；新电脑未建立该库时会明确拒绝，不会用空库掩盖。已完成第2节隔离初始化的组员可直接使用这条**无 QQ、无 AI、无需密钥**的两终端替代命令：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -DataRoot "$PWD\outputs\qq-m3-real-test" -NoBot -NoAssistant -InteractiveScenario -OpenBrowser
```

不依赖任何正式库。已有演示/知识资料如需分享，应由数据负责人明确批准后另外处理，不混入源码交接。

## 5. 汇报与复验

对组员说明两个入口、场景菜单、SIMULATOR 来源、QQ 只读权限和审批预算即可。真实验收逐项确认 General、当前水质、追问、清空会话和正常退出；记录 QQ API 接受与客户端实际显示两种不同证据。不要把本机测试通过描述为生产发布。

日志/报告路径以启动输出 `STACK_STARTING` 为准；只分享脱敏摘要。停止后不恢复旧 Run 额度、不自动重发旧消息；需要继续时按新运行重新批准。
