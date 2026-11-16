---
name: westlake-survival
description: "面向西湖大学师生的校园服务聚合工具包（学业、Canvas、图书馆、研讨室预约、班车、校历、生活网点与校内大模型）。"
license: PolyForm Noncommercial 1.0.0
metadata:
  version: "1.1.0"
  author: yizhang-dream
---

# 西湖大学服务工具包（westlake-survival）

本手册专为 AI 编码代理（ZCode / Claude Code / Cursor / Codex）设计。当用户询问西湖大学相关事务时，调用本工具包命令或 Python API 获取真实数据并执行受控操作。

## 核心行为准则（Agent 必读）

1. **接手第一步**：先执行 `westlake doctor`（支持 `--json`），按输出定位缺失的依赖或配置；插件与 MCP 挂载自检运行 `westlake skill status` / `westlake skill mcp-config`；账号由用户在本地设置页填写；
2. **只读直接执行，写操作受控放行**：查询类命令直接运行返回结果（高频只读命令如 `context`、`digest`、`find`、`probe`、`timeline`、`sis schedule|grades|exams`、`canvas courses|grades|deadlines|todo|assignments|files|discussions|announcements|inbox`、`booking types|list|slots|mine`、`lib search|loans` 均支持 `--json` 结构化输出）；所有写操作（交作业/发帖/预约/续借/打印等）受 Action Card 安全门拦截，必须先向用户汇报潜在影响并获取确认；
3. **预检与票据闭环**：写操作加 `--dry-run` 生成 Action Card，经用户授权后保留相同业务参数并加 `--ticket <ticket>` 执行。票据绑定操作、目标和参数，15 分钟内单次有效；修改参数须重新预检、确认；
4. **按命令降级**：`calendar today/week/events`、`transit next/table` 与 `timeline [--offline]` 支持 `--offline`，可返回本地快照，并应说明快照来源。SIS、AMS、Canvas 等命令不接受该选项；联网失败时如实报告，不把缓存当成已验证的实时结果；
5. **凭据单一存储与绝对保密**：凭据优先存本机系统钥匙串，绝不在控制台打印学号与密码明文；未配置时引导用户运行 `westlake` 打开本地网页填录，Agent 绝不代填；
6. **网络直连规范**：校内请求默认绕过代理，外部脚本调用应使用 `direct_session()`。

## 场景与能力路由表

| 用户场景与意图 | 推荐命令 | 离线支持 | 说明与常见参数 |
| :--- | :--- | :---: | :--- |
| **今日日程与行动流** | `timeline [--offline] [--json]` / `timeline list [--json]` / `timeline add|done|delete` | ✓ | 合并当天课表、Canvas 截止、预约、班车与备忘，去重平行教室并检查时间冲突 |
| **课表与考试** | `sis schedule` / `sis grid` / `sis exams` | — | SIS 本科生教务课表、周网格冲突图与考试日程 |
| **教学系统课表** | `ams schedule` / `ams status` | — | 新版教学系统 AMS 课表（研究生/部分本科）与当前教学周 |
| **Canvas 作业与截止** | `canvas deadlines` / `canvas todo` | — | 在修课程作业、测验倒计时与个人待办事项列表 |
| **作业详情与评分细则** | `canvas assignment-info --course <名> --assignment <名>` | — | 查看具体作业题目说明、附件下载链接与 Rubric 评分标准 |
| **Canvas 课程与文件** | `canvas courses [--past|--all]` / `canvas files --course <名>` | — | 获取在修与过往结课课程 ID、讲义课件与资料列表 |
| **OneDrive/SharePoint 讲义** | `share files --name <名>` / `share download` / `share login` | — | 列出与下载教师分享文件（支持匿名与西湖组织登录会话） |
| **讨论区与收件箱** | `canvas discussions --course <名>` / `canvas inbox` | — | 课程讨论区主题、全班回帖与站内信收件箱 |
| **图书馆书目检索** | `lib search <书名/关键词>` | — | 阿法迪云图书馆检索（书名、作者、索书号、馆藏地） |
| **在借图书与应还** | `lib loans` | — | 查看当前借阅中的图书条码、到期应还日期与续借状态 |
| **在线图书续借** | `lib renew <图书条形码>` | — | **写操作**：办理图书到期续借延期（通常限 1 次） |
| **自习室/研讨室智能推荐**| `booking recommend [--date today] [--time 14:00] [--min-hours 2]` | — | 复合求解连续可用房间时段，直接给出单次预约预检指令 |
| **场地预约状态查询** | `booking types` / `booking list --type <类>` / `booking slots <房间>` | — | 预约中心研习仓、研讨室、自习室可约时段与空闲格子 |
| **场地预约与取消** | `booking book <房间> --date … --start … --end …` / `booking cancel <单号>` | — | **写操作**：研习仓/研讨室提交预约或释放名额 |
| **班车时刻与下一班** | `transit next --campus 云谷` / `transit table --campus 云谷` | ✓ | 三校区班车时刻表与下一班发车倒计时 |
| **今天几号 / 第几周 / 放假**| `calendar today` / `calendar week <N>` / `calendar events` | ✓ | 官方校历当前学期、教学周次、调休补课与节假日安排 |
| **校园网点与后勤生活** | `campus services --campus 云谷` / `campus dining` | 本地数据 | 超市、快递驿站、干洗、理发、文印网点位置与营业时间 |
| **自助文印网点与打印队列** | `pms stations` / `pms jobs` | — | 打印机网点与实时状态（免登录）、我的待打印作业与 ID；上传后到任意自助机刷卡两次取件 |
| **学术数据库与 DOI 论文**| `scholar dbs` / `scholar doi <DOI> -o paper.pdf` | 仅数据库目录 | 订阅数据库本地目录、校外 CARSI SSO 与联网全文下载 |
| **HPC 集群免费 AI 对话**| `hpc chat "<内容>"` / `hpc sync-key` | — | 调用校内 GPU 集群进行 DeepSeek/GLM/Qwen 对话；需账号或已配置令牌 |
| **办事大厅与表单直达** | `affairs apps [关键词]` / `portal ask "<问题>"` | — | 查找办事流程与直达表单链接，或向官方办事 AI 咨询问答 |
| **数据市集 / 个人履历** | `market catalog|profile|resume|courses|honors|clubs|volunteer` | — | 数据目录与本人档案、履历、已修课程、荣誉、社团、志愿概要（脱敏输出，细节见[只读指南](references/data-market.md)） |
| **全校服务探测与状态** | `probe [--json]` / `vpn status` | — | 检查服务可达性与深信服 VPN 连通状态 |
| **按关键词找能力** | `westlake find <关键词> [--json]` | 本地索引 | 按关键词匹配 CLI、MCP、网页与学术库入口 |
| **插件与 MCP 状态** | `skill status` / `skill install` / `skill mcp-config` | 本地 | 检查 ZCode/Claude/Cursor 挂载同步状态，导出 MCP 配置 JSON |

表中 ✓ 表示支持显式 `--offline`；“本地数据/索引”无需联网，也不接受该选项。其他命令即使有缓存，也不能保证可强制离线执行。

## 门户数据市集（按需）

查询数据目录或本人档案、履历、已修课程、荣誉、社团、志愿时，优先运行 `westlake market <query>`（或调用 MCP 工具 `market_query`），命令默认只输出目录元数据或条数与字段名以避免向终端回显证件与联系方式。需要按任务读取具体业务字段时，按[数据市集只读指南](references/data-market.md)在 Python 进程内调用 `westlake_survival.market.MarketClient`（或技能内 `scripts/data_market.py`），复用本机已配置账号。

学分进度、论文/专利、一卡通、财务等目录项仍需核实明细权限，不能作为已接入能力；不要通过申请入口发起流程或改查其他人员。

## 受控写操作规范（Action Card 保护）

当 Agent 遇到需要写入学校系统的操作时，**严禁未经用户审查直接执行**。

| 操作命令 | 潜在影响与后果 | 审查要点 |
| :--- | :--- | :--- |
| `canvas submit --course … --assignment … --file …` | 教师与助教立即可见；误交需重复提交覆盖 | 确认课程名、作业名与文件路径正确 |
| `canvas reply --course … --topic … --text …` | 全班师生可见，通常无法撤回 | 核对讨论主题与回复文案 |
| `canvas send --conversation … --text …` | 收件人立即可见 | 确认收件会话与私信内容 |
| `canvas upload <本地文件路径>` | 上传至个人 Canvas 文件网盘 | 确认文件类型与大小配额 |
| `canvas star <课程名>` / `canvas unstar` | 调整个人面板置顶展示 | 仅影响个人视图 |
| `canvas dismiss-todo <作业ID>` | 归档个人待办事项 | 不改变系统内作业截止时间 |
| `pms print <文件> [--copies N] [--duplex] [--color] [--from-page N --to-page N]` | 上传至联创云打印队列；**刷卡取件前不扣费**，传错可撤单重传 | 核对份数、单双面、彩色与页码范围 |
| `pms cancel <作业ID>` | 从未打印队列中取消作业（刷卡前无损撤回） | 确认作业 ID |
| `booking book <房间> --date … --start …` | 占用研讨室名额，爽约影响信用 | 核对校区、房间名、日期与开始结束时间 |
| `booking cancel <预约单号>` | 释放已预约名额，原时段需重新抢约 | 确认预约单号 |
| `lib renew <图书条形码>` | 延长借阅还书期限（通常每本限 1 次） | 核对图书条码与到期时间 |
| `calendar export [-o schedule.ics]` | 导出课表至本地 .ics 文件 | 确认导出文件名 |
| `timeline add <内容>` / `timeline done <ID>` / `timeline delete <ID>` | 新增、完成或删除本地个人备忘 | 核对内容、日期与备忘 ID |

### 写操作执行闭环
1. Agent 第一次调用写命令时，加 `--dry-run`（例如 `westlake lib renew 123456 --dry-run`）；
2. 命令将输出带有 `Action Card` 的 JSON/格式化卡片，包含风险等级与一次性放行凭证（Ticket）；
3. Agent 向用户展示卡片内容与潜在后果，询问是否执行；
4. 获得用户明确肯定答复后，Agent 保持与预检相同的业务参数，加 `--ticket <ticket>` 完成执行；票据过期或参数变化时重新预检。`--yes` 也只可用于已授权的操作。

## 常见排障与自愈（Agent 指引）

- **网络连接失败或 502**：校内接口默认直连，勿使用代理；若在校外访问教务、Canvas 或预约，提醒用户启动深信服校园 VPN（运行 `westlake vpn status` 核对）；
- **报认证失败或凭据缺失**：告知用户运行 `westlake`（或终端运行 `westlake setup`）在本地安全页面填入统一账号密码，Agent 绝不在聊天中要求用户发送明文密码；
- **图书不可续借**：可能是图书已被其他读者预约、已达到最大续借次数或账号有逾期欠费，指导用户查看 `westlake lib loans` 中的详情说明。
