# 事件生命周期与首页异常概况

从 Prototype 已验收的 EVT-1/EVT-2 及文案收尾选择性同步；Management 独立回归。仅用于 SIMULATOR / PROTOTYPE 规则，不代表疾病确诊或生产告警闭环。没有 ACK、人工关闭或 Snooze。

## 视觉恢复

| 新观测 | 生命周期 |
|---|---|
| 首次可靠 HIT | 创建 ACTIVE |
| 同设备、通道、code、规则再次 HIT | 更新同一事件 ID |
| 连续第 1、2 个可靠 CLEAR | 保持 ACTIVE，显示恢复观察中 1/3、2/3 |
| 连续第 3 个可靠 CLEAR | RESOLVED，保存恢复时间和批次 |
| 恢复观察期间再次 HIT | 恢复计数归零，保留 ID |
| 消退后再次 HIT | 新事件周期 |
| 缺测、无效、部分覆盖无信号、过期、离线 | 不作为 CLEAR，不跨中断累计 |

三个窗口是本地实验参数，不是专业疾病恢复标准。可靠连续证据要求：完整有效、fresh/online、同 Session、Sequence 恰好递增 1、窗口首尾相接、前一观测在本次接收时未过期。新 Session 不单独关闭事件或新建重复周期；其首个可靠 CLEAR 从 1 重新观察。

恢复进度保存在原 events JSON payload，随 current/history/alerts 在 BEGIN IMMEDIATE 中整体提交；重启后继续校验连续性。查询不推进 CLEAR、不落盘。重复或乱序批次不推进恢复。缺失视觉通道的报文会记录中断水位，更早的迟到数据不能恢复当前确定性。

水质阈值和原恢复判定不变。SQLite user_version 仍为 1，没有 Schema 迁移或旧记录重算。旧 payload 兼容读取；缺少恢复元数据时，新 CLEAR 从 1 开始。

## 留存与页面

保留全部 alerts 关联的未结束事件，另保留最近 300 条未关联历史；总数可超过 300。长期归档未实现。

首页独立显示所选设备当前未结束风险，包含恢复观察和证据不足，不受历史列表筛选影响。同族等级合并展示，详情保留原始记录。无活动事件时，必须水质和视觉均完整、新鲜、在线且未命中规则，才显示“当前未见异常信号”；否则显示未知。

视觉 RESOLVED 仅说明连续可靠观测未再检出信号，不代表疾病治愈或人工处理完成。具体状态文案、等级关联、历史筛选和删除保护见 [事件管理](EVENT_MANAGEMENT.md)。

## 离线验证

在 Management 根目录运行：

```powershell
.\.venv\Scripts\python.exe -I -B scripts/dev/run_management_tests.py
```

入口阻止旧 fishery_ai 导入，将 TEMP/TMP 置于 outputs/test-tmp，使用临时 SQLite、虚构数据和 Fake SDK。不得用真实实例开展删除测试。
