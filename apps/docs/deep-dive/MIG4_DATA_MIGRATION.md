# MIG-4B：正式业务数据受控迁移

当前阶段：**正式业务数据迁移及独立只读复核已完成，人工页面验收待进行**。用户在独立 PowerShell 执行得到 MIGRATED_AND_VERIFIED，随后 --verify 返回 VERIFIED_READ_ONLY。正式目标已经存在，不应再次执行 dry-run/apply 迁移流程；下方迁移命令保留为操作记录。

Codex 中此前用户目录安全检查返回 ENV_PERMISSION_ERROR；用户独立 PowerShell 检查通过后完成迁移。没有修改 AppData ACL、Credential Store 或安全规则。

认可的 Git 基线：`6e67202ba1cafae87bac0375e63a6a177789f38e`。所有维护命令使用新项目自己的 .venv。脚本默认 dry-run，无模型/NPU请求，不读凭据，不初始化数据库，不启动 Web 或 Simulator。

## 本次执行回执（2026-10-19）

| 项目 | 实际结果 |
|---|---|
| 迁移ID | `20261019T072850Z-8a9f4ce4be80` |
| 正式目标 | `C:\Users\HP\AppData\Local\FisheryManagement` |
| 保留备份 | `C:\Users\HP\AppData\Local\FisheryManagement.mig4b-backup-20261019T072850Z-8a9f4ce4be80` |
| 原暂存路径 | `C:\Users\HP\AppData\Local\FisheryManagement.mig4b-stage-20261019T072850Z-8a9f4ce4be80`，整体发布后已不存在 |
| 回执 | 备份目录中的 `manifest.json`、`verification.json` |
| 源身份 | manifest 的 source_unchanged=true；stage_verified=true |
| Monitoring | user_version=1，batches/history/current/events/alerts/channel_contacts 为 1440/720/2/36/2/2 |
| Knowledge | user_version=2，32条；全局revision=3，迁移标记 unified-knowledge@2 |
| Settings / Policy | 原字节保留；budget_revision=5，Normal覆盖2048、Streaming默认512；管理generation=11，三个只读工具授权不变 |
| 应用只读检查 | Bootstrap与Knowledge均200，knowledge_count=32；Repository路径均位于正式目标 |
| 模型 / Simulator | provider_requests=0；simulator_started=false |

用户提供的独立 --verify 输出确认五个文件通过。随后 Codex 只读核对备份回执、正式五文件的SHA-256，全部与 verification.json 一致，未再次迁移或写入用户数据。SQLite文件哈希相对源库发生变化符合Backup API行为，逻辑数据与Schema核验通过；三份JSON哈希与源完全一致。

本次代码侧仅新增迁移脚本、专项测试和本文档；18项虚构数据离线安全测试通过。尚未自动启动Web、Simulator或进行网页Key测试。下一步仅进行下文“页面验收与启动”的只浏览验收，保留备份；真实Provider测试与Simulator写入另行执行。

## 文件边界

唯一源根：`D:\CodexProject\Fishery_AI_Prototype`，仅使用 ManagementPaths 的五个实际源文件：

| 来源（相对源根） | 目标（相对正式数据根） |
|---|---|
| outputs/management_web/monitoring.sqlite3 | monitoring.sqlite3 |
| apps/knowledge_data/knowledge.sqlite3 | knowledge.sqlite3 |
| outputs/management_web/settings.json | settings.json |
| outputs/tool-policies/management_assistant_policy.json | tool-policies/management_assistant_policy.json |
| outputs/tool-policies/tool_policies.json | tool-policies/tool_policies.json |

正式数据根由 `ManagementPaths.resolve(..., user_data=True)` 得到，本机为 `C:\Users\HP\AppData\Local\FisheryManagement`。不得选择 outputs/management_web 下的旧 v0 知识库。旧 .env、Credentials、Trace、锁文件及整个 outputs 不迁移。源仓库 Git 和 D:\Fishery_Project 不写入。

## 安全执行条件

- 相关 Web、Simulator、SQLite 编辑器及其他写入器须全程停止。脚本不杀进程。未知 Python/SQLite 进程默认阻止；`--unrelated-pid` 只能由用户明确确认无关后使用，不能忽略命令行已引用鱼业项目的进程。
- 本次用户已确认 PID 34956、14028 是独立 terminal_dojo，与五个源文件无关。它们退出或 PID 状态变化后，应重新核对，不能把该参数当作长期白名单。
- Windows GENERIC_READ / FILE_SHARE_READ 句柄同时覆盖五个源文件，拒绝已有及新开的写入、删除句柄。无法取得句柄即停止，不使用持久化源锁文件。
- 源库须为完整、静止的 rollback/delete 格式，无 WAL、SHM、journal。发现边车、WAL 格式、版本/数据变化就停止，请求独立处理；不删除边车、不 checkpoint、不自动恢复。
- 五个源文件 SHA-256 必须与 MIG-4A 固定基线相符；变化不得仅靠重新生成计划继续。
- LOCALAPPDATA 须与 Windows 已知用户目录一致，位于支持 ACL 的可信本地卷；现有路径不得包含 junction/symlink/多硬链接文件。父目录安全检查失败时退出，不能提升权限、改 ACL 或改用临时根模拟正式迁移。
- 新备份/暂存根及其子目录、文件采用已有 secure_files 的当前用户/SYSTEM 私有权限；只创建新对象，不修改任何现有 ACL，不复制源 ACL。

## 用户普通 PowerShell：dry-run

从开始菜单独立打开普通 PowerShell，不用管理员权限。以下变量只在当前会话内保存，计划不写文件。

```powershell
Set-Location -LiteralPath 'D:\CodexProject\Fishery_Management'
$python = 'D:\CodexProject\Fishery_Management\.venv\Scripts\python.exe'
$migration = 'D:\CodexProject\Fishery_Management\scripts\maintenance\migrate_management_data.py'
# 两个 PID 仅因本次已经人工确认无关而加入；实际执行前重新核对。
$unrelated = @('--unrelated-pid', '34956', '--unrelated-pid', '14028')
$plan = & $python -I -B $migration --dry-run @unrelated | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $plan.status -ne 'DRY_RUN_READY') {
    $plan | ConvertTo-Json -Depth 20
    throw '迁移预检未通过，停止；不修权限、不重试实际迁移。'
}
$plan | Select-Object status, plan_sha256
$plan.plan | Select-Object migration_id, target, backup, stage
$plan.plan.snapshot.semantic.settings
$plan.plan.snapshot.semantic.management_policy
$plan.plan.snapshot.semantic.local_trial_configuration
```

本轮真实 dry-run 确认：Monitoring user_version=1，batches/history/current/events/alerts/channel_contacts 为 1440/720/2/36/2/2；Knowledge user_version=2，32条（31 builtin、1 user，全部 ACTIVE），全局 revision=3。Settings schema=2、budget_revision=5、Streaming偏好，Normal覆盖2048。管理 Policy generation=11，独立三工具授权。内存配置解析得到 Normal/Streaming 2048/512，均 local_experimental；未发模型请求。五文件与 MIG-4A 哈希一致。

`DRY_RUN_BLOCKED_ENV` 只表示已完成只读检查但当前环境不允许写入；不能作为 apply 批准。需要在普通终端重新取得 DRY_RUN_READY。计划绑定脚本哈希、源数据摘要、Git HEAD、操作ID和目标位置；脚本或源变化必须重做预检。

## 实际执行与单独复核

审阅上述计划，并确认写入器保持停止后，在同一普通 PowerShell 会话执行：

```powershell
$result = & $python -I -B $migration --apply `
    --migration-id $plan.plan.migration_id --plan-sha256 $plan.plan_sha256 `
    --writers-stopped @unrelated | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $result.status -ne 'MIGRATED_AND_VERIFIED') {
    $result | ConvertTo-Json -Depth 20
    throw '迁移停止；保留所有产物，不删除或重新初始化。'
}
$result | Select-Object status, target, backup, stage, stage_exists
& $python -I -B $migration --verify `
    --manifest (Join-Path $result.backup 'manifest.json') @unrelated
if ($LASTEXITCODE -ne 0) { throw '迁移后只读校验失败，停止并保留数据。' }
```

每次操作的两个新目录位于同一个 LOCALAPPDATA 父目录：

- `FisheryManagement.mig4b-backup-<唯一ID>`：保留五文件一致备份、plan.json、manifest.json、verification.json；失败时尽力新增 failure.json（安全错误类型和阶段，不记录原始异常/业务正文）。不会自动删除。
- `FisheryManagement.mig4b-stage-<唯一ID>`：五文件完整暂存实例及空 logs 目录。全部验证通过后，以 Windows 不覆盖已有目标的 os.rename 整体发布；成功后该路径不再存在。

SQLite 使用 Backup API，不通过导出重建业务记录。完整SQL Schema、user_version、全部表列/行数/内容摘要及Knowledge元数据必须一致；JSON必须原字节一致。SQLite Backup会给目标分配新的 schema_version cookie，cookie及文件哈希不要求等于源；Schema定义和应用版本没有放宽。

发布前后均校验源身份不变。目标被抢先创建时，不覆盖空目录也不覆盖非空目录。发布后再次检查五文件及实例兼容性，Flask内存GET的 Bootstrap/Knowledge须200，显示原知识数量。只读Repository使用 query_only/immutable 连接；Provider与Trace为禁止I/O适配，没有启动服务或Simulator。单独 --verify 只读正式目标和对应备份清单，不回读旧源，也不补写清单。

若返回 STOPPED，退出码为2。发布前失败则正式目标不存在；失败阶段和相关路径可从已保留的备份清单检查。发布后失败保留正式目录及所有新数据；不得从备份覆盖已产生写入的库。不能用同一操作ID覆盖失败产物，不自动回滚或恢复旧项目写入。

## 页面验收与启动

**现有 run_local.ps1 没有“只启动 Web、不启动 Simulator”选项。** 它总是经 local_session 启用 ingestion 并启动 Simulator；即使 -NoAssistant 也会写监测数据。页面只读验收前不要用它。

迁移校验成功后，用户可在普通终端只启动Web，开启原有Qwen三工具Normal/Streaming范围，同时不启用ingestion：

```powershell
& 'D:\CodexProject\Fishery_Management\.venv\Scripts\python.exe' -I -B `
    -m apps.management_web --project-root 'D:\CodexProject\Fishery_Management' `
    --user-data --enable-assistant --assistant-multi-round-trial `
    --assistant-streaming-trial --assistant-history-trial --assistant-tools-trial
```

访问 http://127.0.0.1:8766，只浏览知识、历史、设置和授权，不编辑或发送模型请求。历史数据随真实时间变旧，显示 stale/offline 不等于迁移丢失。无密钥时AI请求不可用是预期结果；网页Key测试与保存另行执行。

用户完成页面只读验收，并另行同意Simulator写入后，现有一键命令是：

```powershell
.\scripts\dev\run_local.ps1 -UserData
```

此命令默认开启Assistant、Normal/Streaming/History及三工具local_experimental，**也会启动Simulator并按保留上限淘汰旧历史**；不能在前述验收之前执行。不修改任何发布资格、Prompt、Scope或预算合同。

## 离线验证

脚本专项测试仅在本仓库 outputs/test-tmp 下生成虚构数据，覆盖源写入/删除拒绝、已有写入器、完整备份/暂存/发布、并发目标、失败保留、JSON原字节、SQLite cookie差异、权限/基线/计划门禁、未知进程和独立只读复核。没有用真实源数据做迁移演练。

```powershell
.\.venv\Scripts\python.exe -I -B -c "import sys,unittest;sys.path.insert(0,r'D:\CodexProject\Fishery_Management');unittest.main(module='apps.management_web.tests.test_data_migration',verbosity=2)"
```
