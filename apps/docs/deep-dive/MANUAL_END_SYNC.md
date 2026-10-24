# 人工结束功能复核与Management同步

日期：2026-10-24。按用户“没有真实失联记录，由代理仔细检查，通过后同步”的授权执行。

## Git与范围

- Prototype：main，起始HEAD c6e8a20，起始干净；本轮补充4项测试并修复操作排序，只改manual_end.py、test_manual_end.py和技术文档，未提交。
- Management：codex/mig3-baseline，起始HEAD e6f17c6，起始干净；所有本轮改动均在apps，未commit/push。
- 11个共有文件逐项与Prototype上一共用基线73bcb84核对一致后，才同步对应的功能改动；新增manual_end.py与专项测试。同步后13个源码/测试文件与Prototype当前工作区逐字节一致，没有整体覆盖目录。
- 保留Management原cmd/PowerShell/local_session/demo_instance/windows_job、management_paths和pyproject，逐项与HEAD规范化换行比较一致。未修改品牌、独立数据路径、知识副本、Policy、Credential或AI执行合同。

## 发现及修正

旧实现按acted_at时间戳排序选择最新人工结束。合成复现：第一次结束后服务器校时回退，可靠HIT重新出现，再次失联并人工结束；新操作因时间戳较小被旧操作盖过，返回成功但提醒未结束。

新增周期内递增revision作为人工操作顺序，保存真实时间，不伪造校时时间；无revision旧JSON兼容为既有前缀。回退用例先复现失败，修复后通过。Schema仍v2，不新增表或迁移，不重写任何真实JSON记录。

## 安全及边界

- 只允许因过期/离线/缺测/无效等原因而待核实的风险，有稳定周期整组处理；旧inferred/legacy记录仅处理原始ID，可靠ACTIVE/恢复观察/已恢复拒绝。
- 人工结束与RESOLVED、ACK独立；原事实、alerts链接及恢复时间不改。新HIT/新等级重新提醒，新周期不继承；视觉三窗可靠CLEAR仍由原规则判断。
- 本机门禁、必填原因、严格字段、预览revision、事务内重新评估和幂等请求均验证；同请求并发只一条记录，不同请求并发最多一条成功，SQL失败整体回滚。
- 保存原因、服务器时间、操作来源、人工revision、成员ID和证据快照；只称未认证本机操作。完整快照/请求摘要不随Bootstrap发送。
- 人工历史在重启后保留；单条/批量/ACK周期删除不能绕过，300条自动裁剪及新等级同步保留审计。每周期最多50次，达到后拒绝，不静默丢记录。
- 本轮没有批量结束全部、生产处理工作流、派单、Snooze或AI写入Tool。仍明确命中的数据质量告警不在此版本“待核实风险收尾”范围。

## 实际浏览器验收

本仓库event_preview.py --evt2 --manual-end --port 8792，冻结虚构数据逻辑时钟、临时SQLite，只在outputs/test-tmp，未使用正式或演示实例。

已实际检查：空原因提示且不提交；填写原因后涉及2条原始记录的低氧风险成功人工结束；详情保留等级证据、原INDETERMINATE和空规则恢复时间；原因/时间/未认证本机来源可见。首页当前异常不再显示该低氧风险；历史“已人工结束”筛选只返回1个周期。1440px列表及390px确认框检查正常，窄屏无页面横向溢出；控制台无错误。

[桌面结果](assets/MANUAL_END/management-ended-desktop.png) · [390px确认](assets/MANUAL_END/management-confirm-mobile.png)。截图均为本次Management临时虚构数据，未复制真实数据。

## 使用与数据保护

真实Monitoring已在前次授权维护升级为v2；本次功能继续兼容v2，不需要再次升级或重新初始化。没有访问真实库进行人工结束/ACK/清理，也未对正式/演示Knowledge、Settings、Policy、Credential或Trace做读写验证。

没有真实失联记录也能按[虚构预览命令](EVENT_MANUAL_END.md#验证与人工预览)体验，不必让实际设备或正式实例失联。详情→人工结束此风险→填写原因→确认；结束预览按Ctrl+C。正常应用中若没有符合条件的风险，不出现操作按钮是预期行为。

更新了BUILD_RUN的过时“两库均v1”警告为历史维护完成及当前v2兼容说明；其他启动步骤保留。

## 最终回归结果

| 项目 | 实际执行 | 结果 |
|---|---|---|
| Prototype | `.venv\Scripts\python.exe -B scripts/dev/run_tests.py management-independent` | 542项Python、116项Node全部通过；退出码0 |
| Management | `.venv\Scripts\python.exe -I -B scripts/dev/run_management_tests.py` | 575项Python、116项Node全部通过；退出码0 |
| 专项 | 人工结束14项，包括校时回退、旧JSON、并发请求、新Session三窗恢复、ACK删除保护与DTO脱敏 | 全部通过，包含于上述Python回归 |
| 浏览器 | Management临时虚构实例，1440px及390px | 人工结束、必填原因、首页移除及历史筛选通过；控制台无错误 |
| 静态与范围 | Python语法、`git diff --check`、13个同步源码/测试文件一致性、Management专属启动文件与HEAD对比 | 通过；无冲突；未修改启动器或独立路径机制 |

两次测试的TEMP/TMP均显式指向各自仓库的`outputs/test-tmp`，使用隔离SQLite和Fake SDK；未调用真实Provider/NPU。Management独立回归同时验证Normal/Streaming、三个只读Tool及现有启动生命周期。

临时预览服务已通过专用停止入口关闭，进程退出码0，8792端口无监听；浏览器验收标签已关闭。未保留后台测试服务。

两个仓库均保留未提交改动，HEAD不变。正常使用前重启Management的Web进程并刷新页面；没有符合条件的待核实风险时不显示人工结束按钮。后续人工验收可以使用上方链接中的虚构预览，无需更改真实实例。
