# QQ Bot：配置、运行与排错

QQ的详细机制只维护在本页。首次配置按根目录[开始使用](../../../开始使用.md#6-可选开启-qq-机器人)，日常入口见[BUILD_RUN](../BUILD_RUN.md)，停止和备份见[运行维护](OPERATIONS.md)。

## 当前实现

网页“系统设置 → QQ机器人”集中管理AppID、群和成员OpenID、启用开关、每次模型请求最大输出Token、QQ AppSecret保存及已有接收人的事件提醒开关。未启用网页AI、尚未配置QQ时也能打开。实例、设备和配置目录由服务端固定，浏览器不能提交文件路径。

QQ仍是独立进程：官方Gateway → 程序固定分支/Hybrid路由 → Coordinator/Scheduler → ManagementAssistantService → 原AssistantService/ToolCallingService → Qwen或授权当前水质Tool。与Web复用Agent实现，分别装配，不共享浏览器权限或运行中的Service对象。Web和Simulator不依赖Bot。

新配置采用 `management-qq-continuous-run@1`：当前进程人工批准一次，直到人工停止、撤权或严重故障；不按整次运行时长、累计AI轮数或累计费用停止。普通自然语言可能持续产生费用，Token不是云账单硬上限。

## 网页设置与生效

- AppID是应用ID；群和成员须使用平台OpenID，不是普通QQ号码、群号或昵称。一个明确群、一个实例和设备，最多4名明确成员。
- 默认关闭QQ及AI。填写和保存不会联网、测试密钥、启动进程或发送消息；Bot启动仍须核对并批准本次运行。
- Token默认2048，范围1–4096，控制**每次模型HTTP请求最大输出Token**。当前水质问答可能有两次请求，不能把它解释为整个Turn的合计上限。
- 保存后重启Bot生效。启动冻结Token、身份、设备、Policy和Scope；配置改变使旧授权失效，不在执行中修改共享Service。保存不是自动续批。
- 非敏感设置在同一实例的 `qq-bot-settings.json`；Bot配置在 `outputs/qq-m3-real-config`。没有新增聊天或业务数据库。已有配置须由操作者在页面确认保存，不自动修改实际配置。
- AppSecret在隐藏输入框单独提交，沿用原私有CredentialStore，不存项目JSON或浏览器存储、不回显。读取设置不会访问密钥，页面“未检查”不表示密钥缺失。DashScope Key仍在原API密钥页设置。
- 事件通知只能启用已有同App验证接收人，页面不接受任意接收人路径；新电脑配对仍需维护者协助。

## 自然回答和可信来源

固定查询、帮助、工具能力、常见问候和清空会话由程序处理，不产生模型请求。其他授权自然语言进入现有Agent；不靠不断增加业务关键词分类。只处理平台认证的群@事件，伪造@文本不能触发模型。

新Prompt为 `QQ_MANAGEMENT_NATURAL_DIALOGUE@1`，复用Web系统指令。一般概念可直接自然回答；当前鱼塘的数值、在线、时效或现场风险需要本轮当前水质Tool。工具参数仍恰为 `{}`，设备由服务端绑定。没有Knowledge、历史AI查询、评分、ACK、删除、配置写入或设备控制权限。

新回复不要求General/Water JSON，不再把查询后的模型回答全部替换为固定解释模板。分支仍由实际Tool步骤确定：General通常1次请求0Tool；Water最多2次请求1Tool。自然语言可能有事实错误，有限文字防护只检查部分明显的虚构查询、控制完成和来源冲突，**不是通用逐句事实验证器**。

Water回答附加本轮Tool Receipt生成的系统来源摘要，保留SIMULATOR、设备、观测/评估时间、指标质量、新鲜度、连接状态和规则HIT。stale/offline/missing不能当作当前正常，旧低氧读数不产生新的当前HIT；没有HIT也不能证明无风险。查询不是重新采样。Receipt证明执行过查询，不证明模型每一句都正确。超长或有明显冲突时安全降级，不截掉关键来源说明，也不自动重推理。

## 会话、执行与交付

ConversationStore保存在RAM，按App、群、成员、实例、设备、授权版本和Scope隔离。最多6个成功Turn，空闲15分钟过期，总64会话、每会话24KiB、全局1MiB；重启不恢复聊天。历史只帮助理解话题：新的当前水质问题仍须查询本轮Tool，旧水质数值不成为当前事实。

每个AI Turn继续限定90秒、最多2次模型请求、1次当前水质Tool、零自动重试；一个AI worker和两个等待位置。BUSY、重复消息、未授权成员不能启动模型。QQ原消息回复窗口仍有效，与整次Bot在线时长不同。

每轮有独立Service、Session、RequestHandle和最长90秒的内部TurnLease。当前进程的RunConsent及OS所有权不能从聊天或JSON批准字段伪造。写前审计、检查点失败会停止AI；不恢复旧任务、不重放旧消息。持续模式保留累计统计与磁盘逐Turn记录，RAM只保留近期摘要、活动对象和有界会话，不全程堆积模型/会话对象。

沿用SDK资源租约，确认Client/Stream关闭和请求线程退出。取消请求、本地I/O中断、线程退出及远端停止计算/计费是不同状态；不合作线程仍可能无法强制结束。清理未确认则隔离本Bot进程，不成功Commit或继续请求，不清零门禁重试。独立进程不把隔离状态传给Web。

每个原消息只有一个被动回复Owner。发送前复核身份、Scope、SDK状态和消息期限；未知送达不重发或重推理。只有Backend/Source/Commit成功、SDK安全关闭、QQ API明确接受、发送文本哈希及会话revision匹配后才提交成功历史。失败、取消、撤权、未知交付不追加成功历史；`/清空会话`只清当前成员记忆。API接受与客户端实际显示分别记录。

## 旧有界配置兼容

旧 `management-qq-hybrid-process-run@1`、FAST和双轮合同保持原义，旧JSON解释和有限额度仍可使用。旧 `prepare-demo` 仍是独立合成测试入口；不把旧批准、used标记或Provider回执改成无限许可。旧默认1800秒、5Turn、8.06元预留、每请求2048，仅作兼容说明。

网页明确保存已有配置后生成独立持续合同与当前源码Scope；保留旧配置备份，不改历史批准。Scope准备记录保持candidate、qualification为空；实际联网需要本进程的新人工批准，不能仅修改candidate或can_deliver标记开启。

## 事件通知与设备报告

事件私聊通知默认关闭。启用须同App受控好友接收人及本次明确批准；只发授权设备事件，不由QQ号码或昵称推断身份。Management尚无新接收人的独立配对向导，默认不启用不影响群问答。

SIMULATOR新异常、升级和可靠消退各提醒一次；连续同级HIT和ACK不刷屏，不重放启动前历史。发送前持久化声明，失败、未知及重启不自动重发。每日100次、10秒最多1条是通知防刷屏规则，与AI会话轮数无关。私聊成功不代表群主动权限。

设备联调显式绑定报告目录和设备ID后，Web桥接新鲜异常到Monitoring，Bot沿用已批准私聊通道。设备报告当前仅提醒新异常，不自动判断恢复或伪造升级。设备不进入水质AI工具设备列表，原Simulator路径保持不变；操作只看[设备连接步骤](../DEVICE_INTERFACE_QUICK.md)。

## 排错与验证

| 状态 | 含义 |
|---|---|
| `AI_ADMITTED` | 仅准入，继续看 `AI_TASK_FINISHED` |
| `INVALID_TOOL_ARGUMENTS` | 模型参数不符合 `{}`，不放宽设备绑定或自动补跑 |
| `ASSISTANT_RESPONSE_TRUNCATED` | 达到本轮输出上限，不提交残缺成功历史 |
| `RUN_TURN_LIMIT` / `RUN_BUDGET_EXHAUSTED` / `INVALID_RUN_DURATION` | 旧有限配置限制；在网页确认保存为新持续模式 |
| `QQ_REPLY_API_ACCEPTED` / `QQ_EVENT_NOTICE_API_ACCEPTED` | 平台接受，客户端显示仍需独立确认 |
| `DELIVERY_UNKNOWN` | 不重发、不重推理、不追加成功历史 |
| `MANAGEMENT_SCOPE_REVIEW_REQUIRED` | 源码与配置Scope不一致；维护者审查后网页重新保存，不改旧批准绕过 |
| SDK资源隔离或必要检查点失败 | 停止新AI，保留报告并正常停止，不重置门禁 |
| `MANAGEMENT_BOT_REPORT_SAVED` | 最终报告落盘，分别核对Backend、SDK、交付与History |

`-Check`不读取密钥、打开Monitoring数据库或联网，不能证明平台权限、真实密钥及网络可达性。页面读取与保存也不会联网。Fake/Mock证明执行与故障边界，不能替代真实Qwen的工具选择、自然语言质量及长期运行验收。

真实验收应分别记录一般概念/季节问题/当前水质/话题切换/连续追问/缺测过期/权限拒绝的实际Tool次数、模型请求、Token、耗时、SDK和交付；不能把Backend完成或API接受当作回答质量正确或客户端自动显示确认。

## 本次离线核查（2026-11-06）

- 完整运行原集合892项Python：891通过，1条旧测试仍断言默认5轮；按新默认持续合同更新该断言，并新增显式旧有限配置兼容测试。只修改测试后，相关10项复跑全部通过，当前893项均已有通过覆盖；没有在测试夹具修正后重跑第二遍20分钟全量。
- Node初次因模拟加载器未载入新增QQ设置组件而有39项同源错误；补齐测试模块装配，未改生产代码或原断言，14文件144项重新全过。
- 新模式验证覆盖75轮、跨75小时的模拟时钟、每轮90秒、去重/账本失败、4096 Token的真实SDK类Mock HTTP、五轮混合历史、送达未知、SDK关闭和数据库不变；模拟时钟测试不代表真实连续运行75小时。
- 新网页独立于Web Assistant；非敏感设置的读写检查不访问数据库、密钥或网络，显式AppSecret保存使用原私有Store；通知开关和同App绑定复用通过。当前源码Scope与三份candidate准备资源一致，未提升released资格；222条文档本地链接及diff检查通过。
- 本轮没有真实QQ/Qwen调用、实际凭据读取或实际业务库修改；真实质量和持续运行验收由操作者另行进行。持续运行仍会积累磁盘审计文件，SDK不合作线程与模型事实错误的剩余风险仍在。
