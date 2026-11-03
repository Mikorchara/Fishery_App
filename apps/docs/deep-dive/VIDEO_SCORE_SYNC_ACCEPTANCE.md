# 本地视频、Web 界面与评分 Tool 同步验收

2026-11-03。用户批准 Prototype → Management 选择性同步，包括已验收的实验评分；本轮没有真实 QQ／Qwen 调用。

## 结果与入口

在 Management 根目录运行：

```powershell
# Simulator + Web，带 sample.mp4 与 Web 评分装配
.\scripts\dev\启动视频演示系统.cmd

# Simulator + Web + QQ，带 sample.mp4 与 Web 评分装配
.\scripts\dev\启动QQ视频演示系统.cmd
```

旧无视频入口不改默认行为。新入口共用各自原数据实例：两终端 `outputs/demo-instance`；三终端显式请求对应 `outputs/qq-m3-real-test`。未合并或复制业务数据库。均保留 Simulator 场景菜单，本轮没有引入设备联调模式或真实设备接入。

本机根目录已新增与 Prototype SHA256一致的 `sample.mp4`，约65.8MB；它被 Git 忽略，也不进入发行包。交接需另行附上获准使用的录像。媒体只用于展示，与事件、视觉结果和时间戳独立。

## 实际合入

| 范围 | 文件与行为 |
|---|---|
| 评分 | `ai_service/business_tools/water_quality_score.py`、`score_execution.py`、独立固定资源；最小合入 registry、Service、Source Gate 与 Web AI Adapter；默认不装配，QQ不开放 |
| 视频 | `management_web/demo_video.py`；app与CLI接入显式MP4，固定本机媒体路由、Range／HEAD、文件替换检查、原Host／Origin门禁 |
| Web UI | app、components、styles、index、tool-policy；视频中置、双侧独立收起、专注模式、轮询保留播放器；首页AI优先、最近事件通栏保留；Tool授权紧凑 |
| 启动 | local_session、management_stack、两处PS1参数转发与两个新增CMD；原PID／Job／锁／停止行为保留 |
| 打包 | prepare_management的显式启动器名单增加两个新CMD，排除视频、业务数据与凭据 |
| 测试 | 新评分、媒体、参数／Check测试；追加UI轮询与三终端测试；打包独立导入覆盖新模块 |

没有整体覆盖 apps／static／scripts。Management 独有的 Knowledge 初始化要求、Monitoring-only 工厂、LivePermit 类型、M1 SDK 修复、品牌、数据根与私有凭据路径均保留。未改 Backend Adapter／execution、Agent工具循环、Monitoring规则／Schema、事件生命周期或AI写入权限。此前尚未提交的私聊提醒同步改动保留。

## 验证

- 修改前：完整 Python **754／754**，Node **121／121**；`outputs/video-score-sync-baseline.log`。
- 新增与相关专项：**20／20**；`outputs/video-score-targeted-final.log`。
- 合入后完整独立管理回归：Python **774／774**，Node **128／128**；`outputs/video-score-full-regression.log`。包括原 Web Normal／Streaming、Knowledge、Monitoring、Simulator、事件、QQ、SDK、Windows进程及打包测试。
- 最后补充打包启动器名单后，打包独立导入专项 **1／1**；`outputs/video-score-packaging.log`。
- 真实 Windows 三个独立控制台使用新建合成库、Fake Bot启动，验证MP4 Range、评分装配；停止Bot后Web与Simulator继续运行，最后仅回收本次PID。
- 合成数据浏览器预览：1440px及390px，深蓝视频正常、双侧收起、没有横向溢出；Node另测轮询不重建播放器、保留播放位置与事件详情。截图 `outputs/video-score-desktop.jpg`、`outputs/video-score-mobile.jpg`。
- 本机请求 `-Check`：`STACK_PREFLIGHT_OK`，视频／评分均开启，`credential_checked=false`、`database_opened=false`、`network_requests=0`；`outputs/video-score-actual-check.log`。

首轮Node旧断言仍要求首页视觉占位卡，按新布局更新了标题／卡片预期，原最近事件和详情检查保留。启动测试中的PowerShell解析参数传递及Tool名称断言已纠正，最终专项和完整回归均通过。失败日志保留，没有跳过原测试。

## Scope、本机配置与保护

评分Scope依据 Management 实际源码和 legacy／managed Knowledge 元数据生成，四个 Normal／Streaming 范围均经隔离验证；独立 `local_experimental`，不伪造真实资格。QQ 两份候选准备资源刷新实际实现指纹，仍为candidate、工具仅当前水质。旧批准、used、Provider回执、账本不改写。

本机 `outputs/qq-m3-real-config/request.json` **只更新 `scope_sha256`**；模型、群、成员、设备、数据根、期限、费用和私聊接收人逐项验证不变。未创建新批准，运行仍须本次人工审批。

- 同步前源码及工作树备份：`outputs/video-score-sync-dea0f3f61916`，含 `prechange.patch`、摘要及本次修改文件原版。
- 本机请求防覆盖私有备份：`outputs/qq-bot/sync-maintenance/video-score-cf9e086d875d/request.before.json`，同目录记录变更摘要。含身份配置，不能当普通日志交接。
- 开始时 Prototype：`main / cbfa49a`，工作树干净；结束时保持不变。
- Management：`codex/mig3-baseline / e2ab3c4`；开始已有23项未提交／未跟踪的前轮改动，本轮继续保留。所有同步结果未提交、未push。

## 最小人工验收与回退

1. 正常停止旧服务，在根目录运行一个新增视频CMD，选择场景。
2. 打开视频页，核对播放／拖动／循环、两侧展开收起及窄屏；首页应无旧视觉占位框。
3. 在Tool授权中勾选实验评分保存；Web Qwen显式确认一次模型调用。正常场景核对规则／权重，缺测或离线应不可评分。真实调用由用户执行。
4. 如使用QQ，在本次Bot窗口重新审批；固定查询、AI问答与已配置私聊提醒保持原边界。API接受与客户端显示须分别确认。本轮未新增其真实验收证据。
5. 停止Bot后Web／Simulator应继续工作；最后正常停止整组。

关闭视频或评分可使用原无视频入口，或在手动命令省略相应开关。代码回退须逐项撤销本轮manifest，保留前轮私聊改动；不要对脏工作树使用reset／clean或覆盖整个目录。旧请求备份不能直接配合新Scope运行，应重新Check并人工审批。

仍有边界：MP4是否可解码由浏览器编解码支持决定；录像不是实时分析。评分不是专业养殖标准，模型解释仍需人工核对。QQ保留Management原30分钟运行合同，本轮不扩展无限在线。下一步是Management人工网页／QQ验收，不自动联网。
