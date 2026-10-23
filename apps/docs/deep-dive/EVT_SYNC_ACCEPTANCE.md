# EVT 收尾：Management 安全同步与验收

日期：2026-10-23。Prototype `main@73bcb84`，Management `codex/mig3-baseline@0bf5924`；开始时两边工作树均干净。Prototype 本轮只读，Management 同步结果未提交，未 push。

## 核查结论

- 全部留存原始事件先按可靠 `cycle_reference` 整合，再服务端筛选分页；旧 `legacy-*` 不强行合并。首页与事件列表共用周期摘要，详情保留 code、变化证据、原始ID和ACK。
- ACK 绑定周期、等级 token/序号和人工 revision；同等级持续保留，升级和降级重新待确认，复发新周期不继承。列表为已确认/未确认，结束后表示最后等级的确认，非只要历史有ACK就确认。
- `ack_cycle` 删除检查持久原始状态均 RESOLVED/closed、有合法结束时间、成员完整，无活动告警、外部事件或其他审计引用。预览包含事件数/ACK数/revision；提交 BEGIN IMMEDIATE 重新计算，按RESTRICT引用顺序删除，任何失败全回滚。普通单条/批量及300条裁剪继续保护ACK成员，未解除保护后偷偷清理。
- 活动、恢复观察、未知、无可靠周期身份都不能通过周期永久删除；普通无ACK原始历史仍走原有单条条件，不把旧版结束等同可靠恢复。
- 删除仅涉及该周期 events / event_actions / event_handling_members / event_handling，保留其他周期、设备、历史、批次、当前观测和知识。自动留存仍是原来的非活动、非ACK历史上限，不是全库300条上限；它不包含自动清除ACK的路径。
- 原视觉三窗恢复、水质阈值、时间/异常时读数及当前等级投影不变。恢复标签蓝色。未新增人工关闭、归档、Snooze、AI写入Tool。

## 选择性同步范围

31个逐项核对的源码/测试文件：Monitoring 的周期摘要、ACK、删除、schema/migrate、Repository/Service及7组相关测试；Web的入口/实例检查/事件API，四个static文件和4组HTTP/Node/预览测试；Simulator场景及测试。

Management两处原启动器仅扩展场景：PowerShell ValidateSet；local_session 原 DEMO_SCENARIOS及提示。新场景为菜单7，0或8退出；旧7退出别名改为新场景，避免场景与退出冲突。原六场景顺序不变。对应菜单测试同步更新。

未覆盖整个目录。未同步Prototype启动框架、测试runner、仅空白行差异、无关Domain兼容测试或任何outputs/数据库/截图。保留Management双终端、Job Object、锁、浏览器、Demo知识副本、品牌、正式路径、Credential身份、独立打包维护及现有AI合同。

## 真实库只读预检

| 实例 | user_version | batches | history | current | events | alerts | contacts |
|---|---:|---:|---:|---:|---:|---:|---:|
| `%LOCALAPPDATA%/FisheryManagement/monitoring.sqlite3` | 1 | 1440 | 720 | 2 | 36 | 2 | 2 |
| `outputs/demo-instance/monitoring.sqlite3` | 1 | 729 | 720 | 2 | 2 | 2 | 2 |

两库完整性均ok，无WAL/SHM/journal旁文件，必要v1列齐全，孤立/错误设备通道code的alerts引用为0，foreign_key_check为0。v1尚无人工表，ACK引用不适用。查询使用immutable只读连接，不输出业务正文。进程/端口观察未发现鱼业Web/Simulator或可识别SQLite编辑器；运行中Python为本轮隔离测试。此为时点观察，未来正式维护仍须重新确认全部写入器停止。

源文件SHA-256：正式 `b2443ee062b8305184af3dda5a4f250af0496b65377080ccc3194b31048b2799`；演示 `f1f684e7cee5536b30be2abce8a8f243d3882a14a26d93bc3c5c9a14ddbc9c98`。迁移副本验证前后真实源文件一致。

## 隔离副本升级与兼容

仅用SQLite Backup API生成隔离副本并升级，位置：`outputs/test-tmp/evt-sync-f551711f56/`（Git忽略，包含业务副本，应按业务数据保护，不分发/提交）。保留formal/demo的v1备份、v2副本，脱敏结果在 `verification.json` 与 `application-check.json`。

两份副本均UPGRADED_AND_VERIFIED：原6张表全部列/记录数/逻辑摘要和表Schema摘要一致，新人工表为空，v2完整性和RESTRICT外键检查通过。普通启动拒绝v1的用例通过；升级幂等/备份拒绝覆盖/失败回滚由隔离合成测试验证。Management自身读取升级副本，Bootstrap和周期API均200；没有启用AI或Simulator，未执行副本历史删除。

## 正式升级必须另行批准

当前代码要求Monitoring v2；真实正式和演示库仍v1，普通启动明确报UPGRADE_REQUIRED，双击演示也不能直接使用。不能重新初始化、清空或自动迁移。Knowledge仍保持v2，Settings/Policy/Credential不涉及此次升级。

建议用户分实例批准维护，先演示后正式：

1. 停Web、Simulator、SQLite编辑器，确认无写入，复查路径/链接/旁文件；未知写入器先人工确认。
2. 选择从未存在的本地备份路径，例如同实例目录 `monitoring.pre-evt3a-<唯一ID>.sqlite3`；备份归属当前用户，不改变AppData ACL。
3. 使用本仓库 `apps/monitoring/migrate.py --database <绝对库路径> --dry-run` 先检，再在批准后用 `--apply --backup <全新绝对路径> --writers-stopped`。脚本O_EXCL拒绝覆盖，Backup API一致备份，事务升级且不重算事件。
4. 升级前后核对user_version、完整性、外键、6张原业务表记录数/Schema/逻辑摘要，新人工表初始为空，普通只读页面验收后再开Simulator。
5. 提交前失败保留v1并回滚；提交后有问题立即停写，保留v2、新写入及v1备份。未经批准不恢复、不删除。只有确认升级后无新增数据才能考虑从备份恢复并使用匹配v1旧代码；产生新记录后必须先制定新数据保全方案。

本轮没有运行真实库apply，未创建真实实例迁移备份；用户批准后仍须重新检查当前计数与摘要，不能直接复用今天的时点基线。

## 最小人工验收

无需升级真实库：可用本仓库预览脚本 `python -I -B apps/management_web/tests/event_preview.py --ack-cycles --port 8789`，仅创建自动清理的虚构v2库，10分钟限时，不读取知识/Key，不启用AI/上报。浏览器访问 `http://127.0.0.1:8789/#events`，检查每周期一行、确认列、动态等级名称与蓝色恢复；已结束ACK周期预览会提示事件和确认历史数，活动事件不提供删除。仅对这份虚构库测试删除/取消；Ctrl+C结束预览。

真实演示须先获准升级demo库，随后双击原启动器，选7，等待约5分钟完成快降慢升（全阶段6分钟）；新数据前先只读检查32条演示知识和历史。Normal/Streaming真实聊天连接和Provider测试仍留给用户另行操作，本轮禁止自动调用。

## 本轮最终回归与限制

- Prototype：`.venv/Scripts/python.exe -B scripts/dev/run_tests.py management-independent`：528项Python、115项Node通过，106.391秒Python阶段；工作树保持干净。
- Management：本仓库`.venv/Scripts/python.exe -I -B scripts/dev/run_management_tests.py`：561项Python、115项Node通过，206.088秒Python阶段。独立入口禁止导入旧fishery_ai，Fake SDK验证Normal/Streaming/三只读Tool及执行合同；包含Windows演示生命周期、菜单七场景dry-run、重复启动/端口冲突和演示知识副本保护。
- 测试TEMP/TMP设为各仓库outputs/test-tmp；未连接真实Provider/NPU。真实正式/演示Monitoring最终哈希与预检相同，未删除任何真实事件或ACK；未读写真实Key/Settings/Policy/Knowledge/Trace。
- Git diff检查、改动Python语法、PowerShell语法通过；Management独有cmd、demo_instance、windows_job、management_paths、打包配置与HEAD一致（核对Git换行规范化）。无本轮测试遗留Web/Simulator进程或8766/8767/8789监听。
- 本轮未开启真实实例或进行真实双击/人工浏览器验收；页面行为由独立HTTP/Node验证，最终桌面与390px观感仍由用户在虚构预览中验收。Prototype既有视觉截图没有复制到Management。
- Management最终38个新增/修改文件，均为上述源码/测试、两处既有启动器、菜单测试、4份必要文档；无真实数据进入Git。无commit/push，HEAD保持0bf5924。完成后停止等待用户确认，不执行真实升级。
