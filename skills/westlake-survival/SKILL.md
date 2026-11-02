---
name: westlake-survival
description: "面向西湖大学师生的校园服务聚合工具包（学业、Canvas、图书馆、研讨室预约、班车、校历、生活网点与校内大模型）。"
license: PolyForm Noncommercial 1.0.0
metadata:
  version: "1.0.0"
  author: yizhang-dream
---

# 西湖大学服务工具包（westlake-survival）

本手册专为 AI 编码代理（ZCode / Claude Code / Cursor / Codex）设计。当用户询问西湖大学相关事务时，调用本工具包命令或 Python API 获取真实数据并执行受控操作。

## 核心行为准则（Agent 必读）

1. **接手第一步**：遇到环境疑难时优先执行 `westlake doctor`（支持 `--json`），缺依赖或配置照输出修复；
2. **只读直接执行，写操作受控放行**：查询类命令直接运行返回结果；所有写操作（交作业/发帖/预约/续借/打印等）受 Action Card 安全门拦截，必须先向用户汇报潜在影响并获取确认；
3. **免拼长参数闭环**：写操作加 `--dry-run` 会生成带单次放行凭据 `Ticket` 的结构化卡片，经用户授权后传 `--ticket <ticket>` 即可原子放行；
4. **离线优先与优雅降级**：课表、周次、班车等数据内置本地快照机制。若遇校外无 VPN 或网络波动，加 `--offline` 获取最新快照向用户答复，并提示连接校园 VPN；
5. **凭据单一存储与绝对保密**：凭据优先存本机系统钥匙串，绝不在控制台打印学号与密码明文；未配置时引导用户运行 `westlake` 打开本地网页填录，Agent 绝不代填；
6. **网络直连规范**：校内请求默认绕过代理，外部脚本调用应使用 `direct_session()`。

## 场景与能力路由表

| 用户场景与意图 | 推荐命令 | 离线支持 | 说明与常见参数 |
| :--- | :--- | :---: | :--- |
| **课表与考试** | `sis schedule` / `sis grid` / `sis exams` | ✓ | SIS 本科生教务课表、周网格冲突图与考试日程 |
| **教学系统课表** | `ams schedule` / `ams status` | ✓ | 新版教学系统 AMS 课表（研究生/部分本科）与当前教学周 |
| **Canvas 作业与截止** | `canvas deadlines` / `canvas todo` | ✓ | 在修课程作业、测验倒计时与个人待办事项列表 |
| **作业详情与评分细则** | `canvas assignment-info --course <名> --assignment <名>` | ✓ | 查看具体作业题目说明、附件下载链接与 Rubric 评分标准 |
| **Canvas 课程与文件** | `canvas courses [--past|--all]` / `canvas files --course <名>` | ✓ | 获取在修与过往结课课程 ID、讲义课件与资料列表 |
| **讨论区与收件箱** | `canvas discussions --course <名>` / `canvas inbox` | ✓ | 课程讨论区主题、全班回帖与站内信收件箱 |
| **图书馆书目检索** | `lib search <书名/关键词>` | — | 阿法迪云图书馆检索（书名、作者、索书号、馆藏地） |
| **在借图书与应还** | `lib loans` | — | 查看当前借阅中的图书清单、到期应还日期与续借状态 |
| **在线图书续借** | `lib renew <图书条形码>` | — | **写操作**：办理图书到期续借延期（通常限 1 次） |
| **自习室/研讨室智能推荐**| `booking recommend [--date today] [--time 14:00] [--min-hours 2]` | — | 复合求解连续可用房间时段，直接给出单次预约预检指令 |
| **场地预约状态查询** | `booking types` / `booking list --type <类>` / `booking slots <房间>` | — | 预约中心研习仓、研讨室、自习室可约时段与空闲格子 |
| **场地预约与取消** | `booking book <房间> --date … --start … --end …` / `booking cancel <单号>` | — | **写操作**：研习仓/研讨室提交预约或释放名额 |
| **班车时刻与下一班** | `transit next --campus 云谷` / `transit table --campus 云谷` | ✓ | 三校区班车时刻表与下一班发车倒计时 |
| **今天几号 / 第几周 / 放假**| `calendar today` / `calendar week <N>` / `calendar events` | ✓ | 官方校历当前学期、教学周次、调休补课与节假日安排 |
| **校园网点与后勤生活** | `campus services --campus 云谷` / `campus dining` | ✓ | 超市、快递驿站、干洗、理发、文印网点位置与营业时间 |
| **学术数据库与 DOI 论文**| `scholar dbs` / `scholar doi <DOI> -o paper.pdf` | ✓ | 订阅数据库列表、校外 CARSI SSO 会话保障与全文直接下载 |
| **HPC 集群免费 AI 对话**| `hpc chat "<内容>"` / `hpc sync-key` | ✓ | 调用校内 GPU 集群免费进行 DeepSeek/GLM/Qwen 对话 |
| **办事大厅与表单直达** | `affairs apps [关键词]` / `portal ask "<问题>"` | ✓ | 查找办事流程与直达表单链接，或向官方办事 AI 咨询问答 |
| **全校服务探测与状态** | `probe` / `services` / `vpn status` | ✓ | 全校 90+ 域名存活探测与深信服 VPN 隧道连通状态 |
| **需求模糊自适应检索** | `westlake find <关键词>` | — | 自动模糊匹配 CLI、MCP、Web 页面与学术库最佳入口 |

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
| `pms print <文件> [--copies N] [--duplex]` | 上传至联创云打印队列，终端刷卡扣费 | 核对打印份数与单双面设置 |
| `pms cancel <作业ID>` | 从未打印队列中取消作业 | 确认作业 ID |
| `booking book <房间> --date … --start …` | 占用研讨室名额，爽约影响信用 | 核对校区、房间名、日期与开始结束时间 |
| `booking cancel <预约单号>` | 释放已预约名额，原时段需重新抢约 | 确认预约单号 |
| `lib renew <图书条形码>` | 延长借阅还书期限（通常每本限 1 次） | 核对图书条码与到期时间 |
| `calendar export [-o schedule.ics]` | 导出课表至本地 .ics 文件 | 确认导出文件名 |

### 写操作执行闭环
1. Agent 第一次调用写命令时，加 `--dry-run`（例如 `westlake lib renew 123456 --dry-run`）；
2. 命令将输出带有 `Action Card` 的 JSON/格式化卡片，包含风险等级与一次性放行凭证（Ticket）；
3. Agent 向用户展示卡片内容与潜在后果，询问是否执行；
4. 获得用户明确肯定答复后，Agent 带 `--ticket <ticket>`（或在交互式环境中带 `--yes`）完成最终执行。

## 常见排障与自愈（Agent 指引）

- **网络连接失败或 502**：校内接口默认直连，勿使用代理；若在校外访问教务、Canvas 或预约，提醒用户启动深信服校园 VPN（运行 `westlake vpn status` 核对）；
- **报认证失败或凭据缺失**：告知用户运行 `westlake`（或终端运行 `westlake setup`）在本地安全页面填入统一账号密码，Agent 绝不在聊天中要求用户发送明文密码；
- **图书不可续借**：可能是图书已被其他读者预约、已达到最大续借次数或账号有逾期欠费，指导用户查看 `westlake lib loans` 中的详情说明。
