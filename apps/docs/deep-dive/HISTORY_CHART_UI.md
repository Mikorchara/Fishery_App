# 水质历史趋势图

本功能由 Fishery_AI_Prototype 的图表实验选择性合并，Management 独立运行、独立回归。页面品牌仍为“AI 监测系统”；启动器、正式/演示数据路径、知识副本、Settings、Policy 与 Credentials 机制均不因图表同步而改变。

## 数据与时间范围

- 首页和水质监测页读取 `/api/bootstrap` 内 `monitoring.trend`，复用当前实例的 Monitoring 存储历史，不另建数据源。
- 两张图共用最近 5、10、30 分钟、1 小时、全部存储历史五档，默认仍为 30 分钟；轮询与页面切换保留选择。
- 范围以最后有效观测时间为终点，包含边界，不以电脑当前时间平移旧数据。全部历史指服务器已返回的有界历史，不承诺读取数据库的无限历史。
- 后端 `/api/monitoring/history` 的 channel/limit 接口、采样与历史留存逻辑未改；图表档位不是 AI 历史 Tool 的时间合同。
- 延续真实时间间隔、同时间最后接收项去重，以及无效/缺失、长间隔和会话边界断线，不插值或补 0。

## 单指标节点与交互

半径使用 SVG viewBox 单位，显示尺寸随图表宽度缩放：

| 范围 | 普通半径 | 密集时 |
|---|---|---|
| 5 分钟 | 2.5 | 0.65 |
| 10 分钟 | 2 | 0.65 |
| 30 分钟 | 1.35 | 0.65 |
| 1 小时 | 1.35 | 0.65 |
| 全部历史 | 1.35 | 0.65 |

相邻横向间距小于 `max(2.5, 半径×2+0.5)` 时缩点并降低透明度；1 小时/全部还保留超过 120 点的密集判断，不抽样删点。综合图不随短档位放大，维持 1.35/0.65 的原小点策略。

悬停或点击按最近真实时间定位，显示原始值和单位；高亮半径 4。图表可键盘聚焦，左右键、Home/End 选点，Esc 关闭提示。窄屏图表内部横向滚动，不压缩时间轴。

## 三指标归一化总览

各指标在当前选择范围内独立进行 Min–Max 归一化：

```text
归一化值 = (原值 - 本指标最小值) / (本指标最大值 - 本指标最小值) × 100
常量序列统一显示为 50
```

水温橙色实线，pH 紫色长虚线，溶氧青绿色短虚线；共用无量纲 0–100 轴。Tooltip 显示同一条真实记录的水温 °C、pH（无单位）、溶氧 mg/L；缺失/无效显示“不可用”，不跨时间拼值。

这是趋势总览，不能比较原始大小、实际变化幅度或水质适宜度。短小变化也可铺满 0–100；切换范围或轮询引入新极值会重新计算尺度。各项至少两个不同时间的有效窗口，不足时说明或显示空状态。

现有页面合同没有三个指标共同、完整的业务参考范围，因此不复制诊断阈值到前端、不虚构溶氧适宜上限。未来业务范围归一化需另行定义合同。

## 首页与响应式布局

- 桌面左列：单指标历史、三指标总览；右列：视觉概况、AI 助手入口、连接状态。原组件只移动一次。
- 最近事件位于同一 Grid 的下一行，通过 `grid-column: 1 / -1` 通栏；事件详情与列表入口复用原实现。
- 超过 1000px 时，两列共享行高，左侧两张卡片使用 Flex 分配内容空间。SVG 只在空间内居中，保持 780:276 比例；右侧末卡可容纳反向高度差，末卡底边对齐。
- 不设截图专用固定高度、绝对定位或 JS 测高；不裁切坐标/提示。不超过 1000px 时恢复自然纵向布局；局部滚动不撑宽页面。

## 文件与验证入口

| 文件 | 职责 |
|---|---|
| `apps/management_web/static/view-model.js` | 五档范围、指标元数据、原始与归一化几何 |
| `apps/management_web/static/components.js` | SVG、分档节点、原值 Tooltip、指针/键盘交互 |
| `apps/management_web/static/app.js` | 两图共享选择和首页分组；保留 Management 标题 |
| `apps/management_web/static/styles.css` | 图例、Tooltip、桌面对齐与局部滚动；保留品牌样式 |
| `apps/management_web/tests/chart-ui.test.mjs` | 时间/会话/缺失边界、Min–Max、节点和 Tooltip |
| `apps/management_web/tests/monitoring-ui.test.mjs` | 实际页面选择、组件唯一性、详情与轮询 |
| `apps/management_web/tests/chart_preview.py` | 纯内存虚构数据的本机预览，不打开数据库或凭据 |

在 Management 仓库根执行：

```powershell
node --test apps/management_web/tests/chart-ui.test.mjs apps/management_web/tests/monitoring-ui.test.mjs
.\.venv\Scripts\python.exe -I -B scripts/dev/run_management_tests.py
```

人工预览使用本项目 `.venv`：`python -I -B apps/management_web/tests/chart_preview.py --port 8787`，访问 `http://127.0.0.1:8787/#dashboard`。十分钟后自动退出，也可 Ctrl+C 停止；不是正式启动入口，不启用 AI 或 ingestion。

## 同步边界（2026-10-21）

来源为 Prototype `eefaa4f` 加最终布局修复，目标基线 `75b8685`。四份前端文件逐项合并，仅迁入图表变更；未覆盖 `static/index.html`、Management 的文档与启动配置，未迁入旧 Runtime 或业务数据。

后续开发流程保持：Prototype 实验 → 测试 → 人工认可 → 选择性同步 Management → Management 独立回归。两个 Git 仓库独立，不建立自动覆盖同步。

## 本次验收（2026-10-21）

- 图表/页面专项 23/23 通过；独立完整入口 484 项 Python（161.103 秒）和 96 项 Node 全过，无失败、无跳过，禁止导入旧 `fishery_ai` 的约束继续生效。
- 完整回归包含 Fake SDK、HTTP/SSE、监测/知识/设置/Policy、实例隔离与 Windows 双终端生命周期。隔离实例的两个终端持续上报，关闭任一窗口、强制结束监督进程、重复启动和端口冲突的进程回收验证通过；未双击已有用户演示实例，避免读取正式知识或写入现有演示库。
- 浏览器纯内存 340 条虚构窗口：五档分别显示 31/61/181/340/340 点，单指标半径 2.5/2/1.35/0.65/0.65；综合图保留三色/三线型。点击和键盘均可查看原值/单位，事件详情、筛选与页面切换正常，轮询保留范围。
- 1440、1024px 为两列，末卡底边误差小于 0.01px，事件横跨 Grid；900、390px 为自然单列。四档页面均无横向溢出，SVG 比例保持 780:276；390px 的图表只在自身容器横向滚动。
- 最终截图保存在 Git 忽略的 `apps/management_web/tests/outputs/chart-final/`，完整测试日志在 `outputs/test-tmp/chart-sync-regression.log`。没有真实 Provider/NPU 请求，也未读写正式业务数据库、Settings、Policy 或 API Key。最终人工 UI 验收仍由用户执行。
