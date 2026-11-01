---
name: westlake-survival
description: 面向西湖大学师生的校园服务聚合工具（学业/教学/科研/生活/办事/信息六域）。
---

# 西湖大学服务工具包（westlake-survival）

> ⚡ 本文件由 SkillVM AOT 编译器生成（Target: ZCode, Profile: FRONTIER）。

## 核心纪律与原则

- 默认只读与受控写操作：严禁越界，绝不执行选课、代抢课等任何未授权的系统写操作；
- 事务预览卡片（Action Card）机制：写操作未带确认或加 --dry-run 时，自动输出结构化卡片与单次放行凭据 Ticket；
- 免拼长参数闭环：支持传 --ticket <ticket> 执行放行，单次有效且防重放销毁；
- 离线优先原则：遇校外无 VPN 或网络波动时，自动降级为本地快照并输出时间戳，不生硬报错；
- 凭据单一存储与绝对保密：凭据优先存本机系统钥匙串，绝不在输出中打印学号与明文密码；
- 网络直连规范：校内请求默认 trust_env=False 绕过全局代理，避免内网转发异常。

## 能力路由表

| 用户诉求 | 命令 | 离线支持 | 说明 |
| :--- | :--- | :---: | :--- |
| 今天日程安排 / 时空行动流 / 冲突检测 / 个人备忘 | `timeline [--offline]` | ✓ | 跨系统全天日程融合（课表/作业/预约/班车）、重叠冲突预警与个人备忘（支持离线秒出） |
| 场地空闲智能推荐求解器（避免多次轮询） | `booking recommend [--date ...] [--time ...] [--min-hours ...]` | — | 复合求解连续可用房间时段，给出单次预约预检指令 |
| 今天几号 / 第几周 / 校历事件 / 放假 | `calendar today [--offline] / week N / events` | ✓ | 校历学期、教学周次、调休补课与假期安排 |
| 下一班校车 / 班车时刻表 / 导出日历 | `transit next / table [--offline] / transit ical` | ✓ | 三校区班车时刻与接驳建议 |
| 此刻快照 / 每日快报 | `context [--level terse|normal|verbose] / digest` | ✓ | 聚合日期、周次、事件、天气与作业的一屏速览 |
| SIS 课表 / 成绩 / 考试安排 / 选课车 | `sis schedule / grades / exams / cart / sis grid` | ✓ | 教务系统学业数据查询与周网格冲突预检（只读） |
| 教学系统 AMS 课表 / 周次 / 学籍入口 | `ams schedule / status / menus` | ✓ | 新版教学管理系统课表与学期（走 IAM 统一认证） |
| Canvas 课程 / 作业截止 / 待办 / 题目附件 / 收藏 | `canvas courses / deadlines / todo / assignment-info / canvas star` | ✓ | 在修课程、作业详情、评分细则与面板置顶 |
| 图书馆书目检索 / 在借图书与应还 / 在线续借 | `lib search <关键词> / lib loans / lib renew <条码>` | — | 新版阿法迪云平台公开检索、在借查询与在线续借延期 |
| 场地预约分类 / 资源 / 空闲时段 / 我的预约 | `booking types / list / days / slots / mine` | — | 预约中心研习仓、研讨室、自习室逐格空闲状态 |
| 体育场馆与游泳（独立正元系统） | `sport scenes / sites / days / mine` | — | 体育馆羽毛球/乒乓球/游泳场次可约状态（只读） |
| 学术数据库 / CARSI 校外 SSO / DOI 论文全文 | `scholar dbs / ensure / doi <doi> -o out.pdf` | ✓ | 订阅数据库列表、校外 SSO 会话保障与全文直接获取 |
| 高性能计算 HPC / 免费大模型对话 / 镜像站 | `hpc overview / hpc chat <内容> / mirrors` | ✓ | 调用校内 GPU 集群免费进行 DeepSeek/GLM/Qwen 对话 |
| 网上办事大厅 / 表单直达 / 官方 AI 问答 | `affairs apps [关键词] / affairs app <名称> / portal ask <问题>` | ✓ | 办事流程说明、直达表单链接与权威 AI 办事问答 |
| 全校服务注册表 / 堵点探测 / VPN 隧道 | `probe / services / vpn status` | ✓ | 全站 90+ 服务存活与隧道连通性探测 |

## 受控写操作清单（Action Card 保护）

| 操作名称 | 命令示例 | 风险等级 | 潜在影响 |
| :--- | :--- | :---: | :--- |
| `canvas.submit` | `canvas submit --course … --assignment … --file …` | MEDIUM | 课程侧与教师可见；误交需重复提交覆盖或联系教师重置 |
| `canvas.reply` | `canvas reply --course … --topic … --text …` | MEDIUM | 对全班可见，通常不可撤回 |
| `canvas.send` | `canvas send --conversation … --text …` | MEDIUM | 发送后收件人立即可见，无法撤回 |
| `canvas.star` | `canvas star <课程>` | LOW | 仅改变个人视图展示，可随时取消收藏 |
| `canvas.unstar` | `canvas unstar <课程>` | LOW | 仅改变个人视图，不影响选课与作业提交 |
| `canvas.upload` | `canvas upload <文件路径>` | LOW | 上传本地文件至个人 Canvas 文件云盘，占用个人配额 |
| `canvas.dismiss_todo` | `canvas dismiss-todo <作业ID或关键词>` | LOW | 忽略/归档个人待办事项，不影响作业本身截止时间 |
| `pms.print` | `pms print <文件路径> [--copies N] [--duplex] [--color]` | LOW | 上传至联创云打印队列，终端刷卡取件时才扣费结算 |
| `pms.cancel` | `pms cancel <作业ID>` | LOW | 从云打印队列中取消并删除指定未打印作业 |
| `booking.book` | `booking book <房间> --date … --start … --end …` | MEDIUM | 占用他人可用名额，爽约可能影响信用 |
| `booking.cancel` | `booking cancel <预约号>` | LOW | 释放名额，原时段需重新预约才能恢复 |
| `lib.renew` | `lib renew <图书条形码>` | LOW | 延长图书应还日期，每本书通常限续借 1 次 |
| `calendar.export` | `calendar export [-o schedule.ics]` | LOW | 导出课表至标准 iCalendar (.ics) 文件，写入本地磁盘 |
| `timeline.memo` | `timeline add … / timeline done <ID> / timeline delete <ID>` | LOW | 写入本地行动流，支持增/删/改/勾选完成 |

## 执行建议与最佳实践

1. 遇到模糊需求先运行 `westlake find <关键词>` 自适应命中命令；
1. 日常早间先运行 `westlake timeline` 获得今日全局时空编排行动指南；
1. 寻找空闲自习室/研讨室时，优先运行 `westlake booking recommend` 复合求解，避免多次原子轮询；
1. 校外访问教务或 Canvas 时，若遇离线快照且需最新数据，先检查 `westlake vpn status`；
1. 写操作建议先加 `--dry-run` 获取 Action Card 预览，确认无误后再加 `--yes` 或带 Ticket 闭环。
