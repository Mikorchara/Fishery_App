# Windows 部署与配置

首次下载源码的组员只需先读根目录[开始使用](../../../开始使用.md)。本页保留维护者需要的完整参数、已有实例维护与交接检查。

适用对象：首次接手源码的组员、换电脑或换项目路径的操作者。已经配置好的原机器直接看 [日常启动](../BUILD_RUN.md)。本项目是本机研究/演示应用，不是公网生产部署方案。

## 1. 交付范围与前置条件

提供 Git 源码、`apps` 固定资源、`scripts`、本文档，以及已获使用许可的根目录 `sample.mp4`。视频已允许纳入 Git；不放进 Python Wheel。视频仅供播放，不生成视觉检测或事件。

**不随源码交付：**`.venv`、`outputs`、实际 SQLite、Settings、Policy、Trace、聊天、QQ 身份配置、私有密钥、approval/used/额度日志。需要共享养殖知识时，由负责人单独批准导出，不能复制整台机器的运行目录。

准备 Windows、Python 3.11+、Node（用于前端回归）、Windows PowerShell。下面命令全部在新的 **Fishery_Management 根目录**执行，不要求固定盘符。当前验证环境为 Python 3.12.14、openai 2.54.0、httpx 0.28.1、Flask 3.1.3、websockets 15.0.1；这份源码尚无完整锁定依赖文件，新环境仍须运行回归。

```powershell
Get-Location
python --version
node --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'setuptools>=68' -e '.[qq]'
.\.venv\Scripts\python.exe -m pip check
```

不要复用其他项目的虚拟环境。安装依赖可能访问包索引，但不调用 QQ 或 Qwen。无需 npm 安装或前端构建。

## 2. 先选择一种部署路径

| 路径 | 适用情况 | 新建什么 | 是否联网 |
|---|---|---|---|
| A：纯本机演示 | 先看页面、模拟水质和录像 | `outputs/local-demo` | 不需要 QQ/Qwen |
| B：QQ + Qwen 演示 | 已有批准的机器人、测试群和成员 | `outputs/qq-m3-real-test` 与 `outputs/qq-m3-real-config` | 人工审批运行后才联网 |
| C：已有业务实例 | 已有数据库，需要继续使用 | 不初始化、不迁移 | 取决于人工 AI 操作 |

不用依次完成 A、B、C。选择自己的路径；不同路径的数据不会自动同步。新目录若已存在，先核对用途，**不要删除重建或覆盖**。

## 3. 路径 A：无密钥、无 QQ 的本机演示

只在目标不存在时初始化一次空实例：

```powershell
if (Test-Path -LiteralPath "$PWD\outputs\local-demo") { throw '目标已存在，请使用原实例，不要重新初始化' }
New-Item -ItemType Directory -Path "$PWD\outputs" -Force | Out-Null
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.management_web --project-root "$PWD" --data-root "$PWD\outputs\local-demo" --init-data
if ($LASTEXITCODE -ne 0) { throw '初始化失败，停止核查' }
```

预期：`MANAGEMENT_INSTANCE_INITIALIZED`，创建 Monitoring v2、空 Knowledge 和目录后退出，不启动服务。

以后使用：

```powershell
.\scripts\dev\run_local.ps1 -DataRoot "$PWD\outputs\local-demo" -NoAssistant -ShowTerminals -InteractiveScenario -OpenBrowser
```

在 Simulator 终端选场景；打开 http://127.0.0.1:8766 。需要录像时加 `-DemoVideo "$PWD\sample.mp4"`。此路径不启动 AI，不读取模型密钥；知识库初始为空，可在网页手工添加经批准的资料。

原 `启动演示系统.cmd` / `启动视频演示系统.cmd` 使用 `outputs/demo-instance`：首次会从当前用户正式知识库复制知识，后续复用且要求知识非空。**新电脑没有正式知识库时，先用上述 A 路径；不要创建空的 demo-instance 来绕过检查。**

## 4. 路径 B：创建 Management 自己的 QQ 配置

负责人先提供非敏感的应用 AppID，以及经批准的群/成员 OpenID。它们不是 QQ 号码；昵称和群主身份不能代替授权。QQ 开放平台测试资格由负责人核对，生成本机白名单不等于平台授权。

不要复制 Prototype 或其他电脑的完整配置、数据库、私有 Store、批准和 used 文件。下面命令只建立本机新配置与 SIMULATOR 实例；读取 OpenID 的提示只用于本机，不应截屏公开。

```powershell
if ((Test-Path -LiteralPath "$PWD\outputs\qq-m3-real-test") -or (Test-Path -LiteralPath "$PWD\outputs\qq-m3-real-config")) { throw '目标已存在，请先核对已有配置，不要覆盖' }
New-Item -ItemType Directory -Path "$PWD\outputs" -Force | Out-Null
$qqAppId = Read-Host '负责人批准的 QQ AppID（不是密钥）'
$qqGroupId = Read-Host '批准的群 OpenID'
$qqMemberId = Read-Host '批准的成员 OpenID'
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli prepare-demo --data-root "$PWD\outputs\qq-m3-real-test" --config-directory "$PWD\outputs\qq-m3-real-config" --app-id $qqAppId --group-id $qqGroupId --member $qqMemberId --enable-ai
if ($LASTEXITCODE -ne 0) { throw 'QQ 初始化失败，停止核查；不要重复覆盖' }
```

预期：`MANAGEMENT_ISOLATED_DEMO_CREATED`。生成以下内容：

| 位置 | 用途 |
|---|---|
| `outputs/qq-m3-real-test` | 新 Monitoring v2、空 Knowledge、SIMULATOR 样本及隔离标记 |
| `outputs/qq-m3-real-config/request.json` | 当前源码 Scope、运行上限、成员和配置引用 |
| `access.json`、`ai.json`、`monitoring.json`、`policy/` | 独立权限、绑定与 Policy；不含密钥 |

`--enable-ai` 只是运行准备开关，不是付费调用批准。默认仅一个群、一个实例、`sim-pond-1`，允许明确选择最多四名成员且共享额度；增加成员须负责人重新批准并生成新配置，不能由聊天修改。

### 4.1 先做离线检查

```powershell
.\scripts\dev\Start-QQBot.ps1 -Request "$PWD\outputs\qq-m3-real-config\request.json" -Check
if ($LASTEXITCODE -ne 0) { throw 'Check 未通过，禁止继续 Run' }
```

预期 `STACK_PREFLIGHT_OK` / `MANAGEMENT_QQ_CHECKED_APPROVAL_REQUIRED`；`credential_checked=false`、`database_opened=false`、`network_requests=0`。复核 Provider、Preset、模型、实例、设备、群/成员摘要和 Scope。

当前固定模型为 `qwen3.8-flash` / `dashscope-qwen38-flash-r1`；5 Turn、1800 秒、每轮最多2次请求、每请求2048输出Token、每轮90秒、零重试。每轮保守预留1.611060元，五轮最低8.055300元，默认批准总预算8.06元；**不是实际费用预测或云账单硬上限**。普通自然语言也可能收费。

### 4.2 操作者亲自配置密钥

先以同一实例只启动 Web 和 Simulator，供网页设置使用：

```powershell
.\scripts\dev\Start-ManagementStack.ps1 -DataRoot "$PWD\outputs\qq-m3-real-test" -NoBot -InteractiveScenario -OpenBrowser
```

进入「系统设置 → API 密钥」，通过现有“测试新密钥 → 保存”流程配置 DashScope Key。**测试连接会真实调用模型，必须由操作者主动确认，可能计费。** 勿把 Key 粘贴到命令行、聊天或 JSON。完成后正常停止这组 Web/Simulator，避免下一步端口冲突。

再在隐藏输入处保存 QQ AppSecret：

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.qq_bot.management_cli save-secret
```

预期 `MANAGEMENT_QQ_SECRET_SAVED`。已有密钥且明确需要替换时才加 `--replace`。凭据保存在当前 Windows 用户、当前项目路径对应的私有 Store；**复制或移动项目不会迁移密钥**。历史父目录名称包含 Fishery_AI_Prototype，不代表读取另一仓库。不要手工复制 `.env`。

### 4.3 启动三终端并人工批准

再执行一次 Check，确认成功后：

```powershell
.\scripts\dev\启动QQ演示系统.cmd
# 需要 sample.mp4 和 Web 评分装配时，改用：
# .\scripts\dev\启动QQ视频演示系统.cmd
```

Simulator 终端选场景，Bot 终端核对本次范围并输入屏幕显示的 `APPROVE MANAGEMENT <摘要>`。**不要复制旧口令或自动审批。** 未批准时不连接 QQ/Qwen。`QQ_GATEWAY_READY` 后，授权成员在测试群真正 @机器人。

原普通三终端入口关闭 Web AI；带视频三终端入口启用 Web AI 与独立评分开关。QQ 仍只有当前水质只读工具，不获得评分、Knowledge、历史 AI Tool 或事件写权限。

不需要 QQ 时只启动 A 路径或上述 `-NoBot` 入口。**当前 Management Bot 会在本次运行期限到达后结束，不承诺无限在线。** 额度或期限不能自动续批；再次使用需要新的本次人工审批。

### 4.4 主动事件通知是可选项

默认新配置不带接收人，**不会自动发事件私聊**。当前功能可向已验证的一个好友发送新异常、升级与可靠消退，不调用模型；群聊 AI 和私聊通知是两条不同通道。

Management 当前没有独立的私聊配对探测入口，不能让新组员凭 QQ 号码手填或复制别人的接收人。已有受控接收人配置须由负责人另行授权和绑定；新电脑首次配对流程仍是待补项。缺少它不影响群内被动问答。详见 [QQ 合同与限制](../deep-dive/QQ_BOT.md)。

## 5. 路径 C：已有业务实例

只读核对路径和备份，**不要执行 --init-data 或 prepare-demo**。当前 Monitoring 要求 v2。遇到 v1、缺库、损坏或版本错误应停止；显式维护方法见 [维护与回滚](../deep-dive/OPERATIONS.md)。

仅启动已有正式实例的 Web，不启动 Simulator 或 QQ：

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B -m apps.management_web --project-root "$PWD" --user-data --enable-assistant --assistant-multi-round-trial --assistant-streaming-trial --assistant-history-trial --assistant-tools-trial
```

`--user-data` 指向当前 Windows 用户的 `%LOCALAPPDATA%\FisheryManagement`。不要给模拟启动器加 `-UserData`：它会真实写入该实例。QQ 当前仍只接受显式批准的 outputs 隔离实例，不能擅自改路径接正式库。

## 6. 交接验收与停止

| 检查 | 通过标准 |
|---|---|
| 环境 | pip check 成功；完整 Python/Node 离线回归通过 |
| 页面 | 7个页面正常，浅色/深蓝切换；窄屏可操作 |
| 模拟与视频 | 场景生效，源为 SIMULATOR；录像标为 LOCAL VIDEO |
| Web AI（人工授权） | 当前/历史/知识及可选评分按 Policy 执行，来源和时效正确 |
| QQ（人工授权） | 问候、General、当前水质、追问、清空会话；未授权者不能调用模型 |
| 事件 | 同周期一行；可靠结束后一次删除；活动/未知仍拒绝删除 |
| 资源与报告 | SDK CLOSED、线程退出，QQ API 接受与客户端人工看到分别记录；正常停止报告落盘 |

完整离线验证：

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/run_management_tests.py
if ($LASTEXITCODE -ne 0) { throw '回归失败，停止交接' }
```

三终端从最初编排终端 Ctrl+C 停止；正常退出优先于关窗口，以便保存报告。只关闭 Bot 不停止 Web/Simulator。不得按进程名批量结束 Python。交付前填写：源码提交、Python/SDK版本、实例用途、负责人、测试结果和报告路径；不填写密钥或完整 OpenID。

## 7. 常见阻碍

| 现象 | 处理 |
|---|---|
| 目标目录已存在 | 使用原实例或选择新的明确路径；不覆盖、不重初始化 |
| DEMO_SOURCE_KNOWLEDGE_MISSING / EMPTY | 新电脑先用 A 路径或 B 的 NoBot 入口 |
| 端口占用 / 实例已运行 | 正常停旧服务，或明确选择其他端口；不误杀进程 |
| MANAGEMENT_SCOPE_REVIEW_REQUIRED | 交给维护者核对源码/Scope/配置；不删除门禁或修改旧批准 |
| Check 成功但连接失败 | Check 未测试密钥、平台资格或联网，按安全错误单独排查 |
| 原文件夹直接复制后不能用 | 重建本机 .venv、生成绝对配置、重新录入私有密钥；旧 Run 不复用 |

不在本指南中自动部署公网服务、防火墙例外、远程认证或真实传感器。局域网开发板报告接收见 [设备连接步骤](../DEVICE_INTERFACE_QUICK.md)，真实水质/实时视频方案保留在 [规划文档](../deep-dive/plan/REAL_DEVICE_INTEGRATION.md)。

## 8. 交接签收单

| 项目 | 由交接双方填写 |
|---|---|
| 源码版本 | 提交ID、分支、有无未提交修改；组员拿到的必须包含本次完整改动 |
| 环境 | Windows、Python、Node、SDK版本及pip check结果 |
| 实例 | 数据根、用途、是否空知识库；不记录业务正文 |
| QQ | 负责人、批准的App/群/成员摘要；密钥只在本机录入 |
| 预算 | 模型、Turn/请求/时间/费用上限及人工披露确认 |
| 验证 | Python/Node结果、一次页面验收；真实联网必须单独批准 |
| 停止与交付 | 本次运行目录、报告是否落盘、接收方已会正常停止 |
| 已知限制 | Bot限时、接收人配对缺口、真实硬件未验收、非生产鉴权 |

交付前检查Git状态与视频是否实际跟踪（只核对，不会提交）：

```powershell
git status --short
git ls-files --error-unmatch -- sample.mp4
```

从忽略列表移除视频不等于已经加入Git；显示 `?? sample.mp4` 时仍需负责人在正式提交时显式加入。提交/推送由负责人批准执行，本指南不自动完成。
