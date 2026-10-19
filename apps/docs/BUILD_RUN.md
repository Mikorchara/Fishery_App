# 安装、启动与离线验证

本页命令在 Fishery_Management 根目录执行。Python 3.11+、Node；Flask/SQLite/原生 JS，不需 npm。旧项目 .venv、PYTHONPATH、src、outputs 均不是依赖。

## 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'setuptools>=68' -e .
.\.venv\Scripts\python.exe -m pip check
```

安装依赖可能访问 Python 包索引，不请求 LLM。开发环境只允许本项目自己的 editable 安装。

## 隔离实例与一行启动

MIG-3 不迁移真实数据，不打开正式用户实例。以下创建一个明确的测试实例（目标必须不存在）：

```powershell
New-Item -ItemType Directory -Path outputs -Force | Out-Null
.\.venv\Scripts\python.exe -I -m apps.management_web --project-root "$PWD" --data-root "$PWD\outputs\acceptance-instance" --init-data
```

初始化只建立空白 Monitoring/Knowledge 和必要目录，不导入旧知识、监测数据、设置、Policy 或密钥，不启动服务。已有实例缺库、损坏、Schema不兼容均应报错，不能靠初始化掩盖遗漏。

本轮可用的一行演示命令：

```powershell
.\scripts\dev\run_local.ps1 -Scenario low_oxygen -DataRoot "$PWD\outputs\acceptance-instance" -NoAssistant
```

访问 http://127.0.0.1:8766 。Ctrl+C 停止自己启动的服务器和模拟器。启动器生成一次性 HTTP 接入 Token，不输出/保存；每10秒上报，数据明确为 simulator。端口占用拒绝，不终止未知进程。-Port 可另选端口；-Scenario 支持 normal、low_oxygen、suspected_disease、reduced_feeding、combined_anomaly、device_offline。

本轮实际用 `-Port 18766` 验收，避免占用旧服务；未修改任何未知进程。

-NoAssistant 保证演示不读取真实凭据或请求模型。自动测试中的 AI 使用 Fake SDK，不依赖真实 Key。正式数据迁移和凭据配置获得独立批准后，才可去掉 -NoAssistant 进行用户主动网页验收；启动本身仍不请求模型。

原服务器 CLI 保留全部试用开关，默认关闭；一行启动器仅启用已有批准的 Qwen 范围。-NoStreaming、-NoHistory、-NoMultiRound 可独立收回相关本地试用。不要省略数据根参数使用历史兼容路径。

## 未来正式数据与凭据

数据位置集中在 apps/management_paths.py。--data-root/-DataRoot 是绝对路径；--user-data/-UserData 指向 %LOCALAPPDATA%\FisheryManagement，只有完成后续真实数据迁移后再使用。本轮未在那里初始化或迁移文件。Settings、管理 Policy/同根共享兼容 Policy、Trace 都属于选定实例，不向源仓库回退。

Credentials 保持独立私有 Store，PROCESS_ENV > PROJECT_ENV > MISSING。私有目录仍含历史产品名称，但项目身份由本项目根路径散列决定，因此不自动读取源项目 Key。不要复制 .env，不把密钥放进业务数据、Git、URL、浏览器存储或聊天。后续由用户重新配置或批准专门的凭据处理。

## 离线测试

```powershell
.\.venv\Scripts\python.exe -I scripts/dev/run_management_tests.py
.\.venv\Scripts\python.exe scripts/dev/run_tests.py fast
```

完整入口覆盖 Backend、业务 Assistant、三个 Tool、Monitoring、Simulator、Knowledge、管理 HTTP/SSE、Settings 和 Node；阻断 fishery_ai 导入。TEMP/TMP 自动定位 outputs/test-tmp。人工资格不混入自动回归，不自动发真实请求。

专项直接调用 unittest 时，也应把 TEMP/TMP 指向本项目 outputs/test-tmp；使用虚构凭据和隔离数据，不要运行旧混合工程的 PRODUCT/QUALIFICATION 选择项。本仓库 run_tests 的 management 与 management-independent 都是完整管理集，fast 是管理专项小集合。

## Wheel

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir outputs/dist .
```

需预先安装 setuptools>=68，不能降低 build-system 要求。发行包只含 apps 程序、固定 JSON 和静态资源，不含 tests、development、SQLite、Settings、Credentials、Trace、缓存、文档或运行输出。Python依赖约束与来源版本一致。MIG-2 staging 生成器保留作工程检查；本项目正式构建直接使用根 pyproject。

## 设置与 AI

系统设置仍可管理默认模型/设备/模式、Tool 授权、用户主动连接测试与受控预算；本轮不操作真实配置。当前/历史/Knowledge 来源独立，Qwen已有三工具 Normal/Streaming local_experimental 不因迁移升级为 released。默认 Normal，最多2 Calls/2 Rounds/3 Requests、retry=0、120秒；实际输出预算由已批准配置与用户设置决定。

Preview 未通过 Commit Gate 不进入成功 History；Stop、断流、超时和失败不重试、不切换模式/Provider。主动点击发送只授权当前冻结配置；配置改变使旧 revision 失效。完整合同见 INTEGRATION 与开发指南。

## 真实测试

scripts/manual_real_tests/ 只委托现有管理资格 CLI，默认 dry-run；真实执行需本次精确计划批准。本轮没有真实 Provider/NPU 请求。历史操作记录在 history/，不作为新项目启动前提。
