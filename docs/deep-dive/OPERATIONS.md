# 运行维护、数据保护与回滚

部署见 [部署与配置](../guides/DEPLOYMENT.md)，使用见 [启动指南](../BUILD_RUN.md)。这里的维护命令不属于日常启动，更不表示已经获准对正式库执行。

## 数据位置与版本

路径由 `apps/management_paths.py` 唯一装配。必须明确选择实例；不扫描并自动选用其他项目的数据。

| 用途 | 数据根 | 说明 |
|---|---|---|
| 本机唯一日常实例 | `outputs/qq-m3-real-test` | 五个 cmd 均使用当前 QQ 实例 |
| 旧正式 Web-only | `%LOCALAPPDATA%\FisheryManagement` | 原样保留；仅显式 `--user-data` 选择，日常cmd不使用 |
| 原两终端演示 | `outputs/demo-instance` | 原样保留；仅显式 `-Demo` 选择，日常cmd不使用 |
| 自建隔离演示 | 显式 `--data-root` | 新建一次；以后只复用 |
| 凭据 | 当前用户私有Store、项目路径身份 | 不在业务数据根、不进Git、不自动随文件夹迁移 |

每个数据根包含 Monitoring、Knowledge、Settings、Policy、Trace。Monitoring当前为Schema v2；Knowledge使用 `unified-knowledge@2` 标记，和Monitoring版本不是同一合同。新实例创建最新结构；已有v1不会在普通启动时静默升级。此前正式/演示库升级是历史维护结论，本轮没有再次打开它们，不据此保证任意电脑的版本。

首配入口 `Initialize-Management.ps1` 显式新建完整日常实例：31条随包背景资料、空监测数据、原只读Web工具授权和合成实例标记。原 `--init-data` 的默认空库合同保持不变；旧 `prepare-demo` 仍只新建独立实例，日常接手改用网页“QQ机器人”设置，只生成独立QQ配置，不改变原库，不复制或重置知识和历史。

交接验证：从无outputs/无venv/无密钥的源码副本新建虚拟环境并安装依赖，初始化、31条检索、重复初始化拒绝、同库追加QQ配置、两进程视频与Fake三进程运行/退出均通过；Wheel也能脱离tests夹具初始化31条。完整回归Python856、Node139通过。验证仅用本机模拟数据及Fake QQ/Provider，没有真实联网调用；现有实例未清空。维护报告在本机`outputs/first-run-validation-…/clean-acceptance.json`。

2026-11-05按操作者选择，以现有三终端实例作为日常主库，只调整原两终端cmd指向。未读取或迁移业务记录，未删除旧目录。直接Web/旧CLI不带路径仍有历史兼容默认位置；维护者应显式传入上述日常数据根，避免误开旧实例。私有凭据与QQ批准/运行日志继续按原安全边界独立存放，不迁入业务库。

## 停止、锁和日志

统一Stack复用原Web/Simulator启动器。Web/Simulator配对中任一个正常退出会收尾本次配对，编排器再清理自己的Bot；单独停止Bot不结束配对。只操作本次创建并校验PID/nonce/Job的进程，不批量杀Python。

Stack启动输出 `STACK_STARTING` 的目录（`outputs/management-stack/stack-…`）是本次状态依据：

| 文件 | 用途 |
|---|---|
| `stack.json` | 控制PID、nonce、模式、实例 |
| `web.log` / `simulator.log` / `bot.log` | 分服务日志；分享前脱敏 |
| `<role>.status.json` / `controller.log` | 实际PID、就绪/失败、退出状态 |
| `bot-run/result.json` | Backend、SDK、额度、交付、History、停止与清理 |
| `bot-run` 内批准/账本/检查点 | 审计与去重，不能改写或删used恢复额度 |
| Stack `result.json` | 整体和各进程结果，不等同于Bot成功交付 |

```powershell
# 把路径换为本次 STACK_STARTING 输出；不要猜测别人的运行目录。
.\scripts\dev\Stop-QQBot.ps1 -RunDirectory '<本次Stack绝对目录>'
.\scripts\dev\Stop-ManagementStack.ps1 -RunDirectory '<本次Stack绝对目录>'
```

优先编排终端Ctrl+C，等待有界收尾和报告。强制关终端/杀进程不能保证最终报告落盘；已有写前额度和交付检查点仍保留，不据此重放消息。缺少result.json不能推定未收费或未发送。

## 备份与恢复

事件维护：本机事件页支持“删除此轮事件”和“清空全部事件记录”，可显式删除活动、待核实、ACK及人工结束记录。确认框列出范围与数量；不是清空整个Monitoring数据库，不删除观测历史、原始报告或QQ发送日志。清空不停止监测，后续新异常可再生成事件。具体状态和普通/彻底清理区别见[事件管理](EVENT_MANAGEMENT.md)。维护代码测试只用隔离实例，不把开发授权视为实际清理业务数据的授权。

1. 正常停止所有访问该实例的Web、Simulator、Bot、数据库编辑器，核对没有未知写入。
2. 在新的、不会覆盖的维护目录保存完整实例副本，保留SQLite及其侧文件、Settings/Policy/Trace和已有运行审计；备份按业务数据保护，不能提交Git。
3. 记录源码版本、路径、文件摘要、Schema、记录数和完整性；不公开记录正文、Key或完整OpenID。
4. 运行中不能只复制一个SQLite主文件当作完整备份；使用受控SQLite backup API，或停服后完整冷备。知识库现有backup命令及适用路径见 [知识库合同](KNOWLEDGE_CONTENT.md)。JSON/Markdown导出不是数据库灾备，也没有实现通用回导入。
5. 恢复前再次停写，另存“当前状态”，保护备份后新增的数据；只在负责人批准后置换。恢复到单独路径先验证，不自动覆盖现库。

源码回滚与数据恢复是两件事。回到集成前应使用一个新的干净检出并重建环境，指向验证过的兼容实例；不要用reset/clean覆盖当前工作树，不把老代码直接连上含新审计的库进行裁剪。私有凭据身份与项目根路径有关，回滚目录变化后须由操作者重新配置。

## Monitoring v1 → v2（仅显式维护）

新电脑空实例不需要此步骤。已有库先单独取得维护授权、停写并创建不可覆盖备份。维护工具只读dry-run也会读取指定库，因此不能拿正式路径做普通开发测试。

```powershell
$monitoringDb = Read-Host '已批准维护的Monitoring数据库绝对路径'
.\.venv\Scripts\python.exe -X utf8 -I -B apps/monitoring/migrate.py --database $monitoringDb --dry-run
```

确认schema=1、完整性正常，核对六张原表（current、history、batches、events、alerts、channel_contacts）的数量、Schema摘要和逐行逻辑摘要。版本=2则无需迁移。工具dry-run不是运行进程清单检查，也不代替额外外键/写入进程核查。

**下列apply只有另行批准后才能执行。** 备份父目录必须是可信本机磁盘上已存在的独立维护目录，备份文件必须全新：

```powershell
$monitoringBackup = Read-Host '新的完整备份绝对文件路径（不得存在）'
.\.venv\Scripts\python.exe -X utf8 -I -B apps/monitoring/migrate.py --database $monitoringDb --apply --backup $monitoringBackup --writers-stopped
```

工具取得写事务、创建不可覆盖备份、核对摘要，新增event_handling、event_actions、event_handling_members及索引/外键，升至v2并复核六张原表。不会删除既有事件。维护者另外执行foreign_key_check和新版本接口的隔离读取验证，保存脱敏回执。

预检差异、未知写入、迁移失败或升级后复核异常时立即停止；保留源库、备份和日志，不自动恢复覆盖。需要回退时先保全升级后的新增数据，再决定用旧备份和匹配代码，不能承诺自动无损回滚。

旧跨项目迁移工具 `scripts/maintenance/migrate_management_data.py` 仅用于已获批的旧资料迁移，不是新部署必经步骤；它不会替代Monitoring v2升级。不要重新运行历史迁移来修复当前缺库。

## 离线回归与发行

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/run_management_tests.py
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

完整入口阻断旧fishery_ai导入，使用合成数据/Fake Provider并运行Node测试，TEMP/TMP落在outputs/test-tmp。直接跑专项时也将TEMP/TMP指向该忽略目录。任何真实连接测试不属于自动回归。

制作Wheel（预先准备setuptools>=68，不联网补构建依赖）：

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir outputs/dist .
```

Wheel只带应用程序、固定JSON和静态资源，不含测试、docs、脚本、SQLite、密钥、sample.mp4和运行输出。**本次组员交付优先源码包/Git，不把单个Wheel当作完整三终端演示包。** 在新检出中核对启动脚本和获准视频存在，再按部署指南生成本机配置，不复制整个outputs。

已知技术债：没有完整依赖锁；持续Bot仍有每轮超时与SDK不合作线程风险；本机门禁不是多用户生产认证。QQ配置与接收人配对统一见[QQ说明](QQ_BOT.md)，配对必须由操作者明确批准联网。它们不应在报告中写成已解决。
