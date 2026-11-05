# 部署维护与交接检查

首次下载、安装、初始化和日常配置只按根目录[开始使用](../../../开始使用.md)。日常快捷入口见[BUILD_RUN](../BUILD_RUN.md)，QQ持续运行和旧版兼容只看[QQ说明](../deep-dive/QQ_BOT.md)。本页不重复另一套首配或QQ预算教程。

## 唯一日常实例

安装依赖后显式执行 `Initialize-Management.ps1`，新建 `outputs/qq-m3-real-test`，带31条项目背景资料和空监测历史。两终端、三终端及视频版本共用此实例。没有QQ配置或密钥也能使用Web、Simulator、本地视频和知识页面。

后续QQ在网页“系统设置 → QQ机器人”给同库新增配置，不重建数据库。旧 `prepare-demo` 只保留独立测试兼容用途；不要用它替代日常首配。旧 `local-demo`、`demo-instance`、`--user-data` 都不再是四个日常cmd的默认路径。

| 位置 | 保存内容 |
|---|---|
| `outputs/qq-m3-real-test` | 日常Monitoring、Knowledge、Web设置、Tool授权和日志 |
| `outputs/qq-m3-real-config` | QQ身份、成员、设备绑定及配置引用，不含密钥 |
| `outputs/management-stack`、`outputs/qq-bot` | 启停状态、批准/执行报告、通知去重与接收人绑定 |
| `.local-backups` | 操作者保留的旧outputs；不随Git交付 |
| 当前用户私有Store | Qwen/QQ密钥，按Windows用户和项目路径区分 |

运行库不进入Git。31条固定初始知识资源随源码提供，仅在显式初始化时导入；已有知识、事件和配置不会被初始化覆盖。

## 已有实例与维护参数

已有目录先核对用途和备份，不执行初始化来掩盖缺库或损坏。Monitoring要求Schema v2；普通启动不升级数据库。版本维护、备份与回滚见[OPERATIONS](../deep-dive/OPERATIONS.md)。

维护者可用 `run_local.ps1 -DataRoot <明确实例>` 或 `Start-ManagementStack.ps1 -DataRoot <明确实例>` 选择其他隔离实例；不是日常默认。不扫描并自动切换数据根。

仅打开旧Windows用户实例的Web时可显式使用 `--user-data`；不要给Simulator添加这个参数，以免模拟数据进入旧业务实例。QQ现有准入只允许已明确初始化并绑定的项目outputs实例，不能通过改路径擅自接正式库。

选择运行模式、场景、视频和端口的参数以[启动指南](../BUILD_RUN.md)为准。局域网接收器与设备绑定见[设备连接步骤](../DEVICE_INTERFACE_QUICK.md)。本地视频只是录像，不产生监测事实或事件。

## 凭据与网络

新电脑需要自己的DashScope Key和QQ应用凭据；不要复制别人的私有Store、整个outputs、批准或used记录。移动项目路径不会自动迁移密钥。私有Store的历史父目录名含Fishery_AI_Prototype，但Management按自身项目路径使用独立子目录。

初始化和离线Check不调用模型。网页测试密钥、AI发送和实际QQ连接须由操作者主动发起。Check成功只证明本机配置一致，不能证明QQ平台权限、密钥或网络有效。

QQ新配置采用持续模式和自然回答，Token可在网页设置，保存后重启；新机器先从网页配置，不复制旧批准或私有凭据。机制统一记录在[QQ说明](../deep-dive/QQ_BOT.md)。

## 交接验收

- 用没有原outputs、原venv和密钥的源码副本验证安装与初始化；不能只凭维护者电脑已运行来判断。
- 检查31条知识可检索、模拟数据首个窗口约10秒后上报、视频支持Range读取、重复初始化拒绝覆盖。
- 页面浅色/深蓝与窄屏可用；事件按风险周期展示，本机删除/清空需明确确认。
- QQ单独验证消息接收、回答质量、Tool实际来源、会话记忆和客户端显示；Fake成功不能替代真实体验。
- SDK关闭、线程退出、单次交付、未知结果不重试和停止报告分别核对。
- 交付前记录源码版本、依赖版本、测试结果和负责人；不附真实数据库、群成员完整身份或密钥。

维护者完整离线回归：

```powershell
.\.venv\Scripts\python.exe -X utf8 -I -B scripts/dev/run_management_tests.py
```

Node只用于前端回归，正常运行无需npm构建。当前尚无完整依赖锁，换环境须做验证。

停止时优先在编排终端按Ctrl+C，等待报告写入。单独停止Bot不结束Web/Simulator；不按进程名批量结束Python。交接不包含公网生产认证、防火墙例外或真实设备自动配置。
