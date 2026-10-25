---
name: westlake-survival
description: 西湖大学校园一站式工具（学业/教学/科研/生活/办事/信息六域）。学业：课表、成绩、考试安排、评教、第二课堂、个人信息/学籍/住宿/荣誉/志愿/资助/社团；Canvas：课程、作业截止、考试测验、交作业（写操作）；学术科研：订阅数据库清单、CARSI 校外登录（westlake scholar ensure 一条命令）、DOI→PDF 论文全文下载、科研进展、导师名录、HPC 集群队列、报销与科研经费制度；就业：招聘岗位、招聘会、宣讲会；生活：校历周次与假期、班车时刻、食堂咖啡、公寓、校区地图与全景、自助打印、图书馆借阅；办事：办事大厅目录、我的待办、门户个人卡片；信息：新闻、讲座活动、学院动态、全站搜索、87 服务注册表与在线普查。凡与西湖大学（Westlake）相关的查询或操作需求都可使用——包括但不限于「查/交作业、下周什么考试、几号放假、下一班校车、找论文并下载全文、校外访问数据库、我借了什么书、打印点在哪、报销规定、今天有什么讲座/待办、找某位老师、宿舍与荣誉记录、跑普查找服务」。不确定某需求归哪条命令时，先运行 westlake find <需求关键词>（口语同义词可命中，如「论文」「借书」「放假」）。
---

# 西湖大学生存手册（westlake-survival）

把西湖大学各服务系统收敛为一条 CLI / 一套 Python API / 一个 MCP 服务器。**默认只读**：本技能只做查询与导出；唯一的写操作是 `canvas submit` 交作业（见下），且仅凭用户当轮明确指令执行，不做选课、抢课等其他写操作。

## 能力地图：哪类问题用哪条命令

| 用户想问 | 命令 |
| **不知道这需求归哪条命令 / 这 skill 能干什么** | **`westlake find <需求关键词>`**（搜 CLI/MCP/网页/学术库/服务注册表，口语可命中） |
| --- | --- |
| 今天几号 / 第几周 / 什么学期 / 今日校历 | `westlake calendar today` |
| 本学期第 N 周的起止日期 | `westlake calendar week <N>` |
| 校历事件（开学、假期、考试周） | `westlake calendar events` |
| 下一班校车 / 某校区班车时刻表 | `westlake transit next` / `westlake transit table` |
| 一句话「此刻西湖」（日期+周次+事件+班车+天气） | `westlake context` |
| 每日晨报（快照+活动+班车+周次+Canvas） | `westlake digest` |
| 我的课表 / 成绩 / 考试安排 | `westlake sis schedule` / `grades` / `exams` |
| 待评教任务 | `westlake sis-evals list --pending` |
| 第二课堂成绩单（5 维度 + 每项进度） | `westlake records second-class` |
| 学业导师（分配结果 + 两轮名单） | `westlake records advisor` |
| 学籍异动流程 / 困难认定 / 本博衔接 / 就业状态 | `westlake records other-apps` |
| 我的个人信息 / 学籍 / 紧急联系人 | `westlake profile info` / `academic` / `extended` |
| 住宿 / 请假 / 荣誉 / 志愿 / 实践 / 违纪 | `westlake records dorm` 等（见下） |
| 贷款 / 勤工助学 / 海外交流 / 社团 | `westlake aid loans` 等（见下） |
| Canvas 课程 / 作业截止 / 测验考试 | `westlake canvas courses` / `deadlines` / `exams` |
| 列出某课程的作业（查作业 id/名称） | `westlake canvas assignments --course <id或关键词>` |
| 交作业（文件/文本/链接，写操作） | `westlake canvas submit --course … --assignment … --file 路径` |
| 查看某作业已提交状态 | `westlake canvas submission --course … --assignment …` |
| 讲座 / 学术会议 / 演出预告 | `westlake events` |
| 西湖新闻 / 科研进展 | `westlake news` / `westlake research` |
| 本科培养方案 / 课程体系 / 专业介绍 | `westlake program plan [专业]` / `curriculum` / `majors` / `overview` |
| 某门课几学分、哪个专业有、先修是什么 | `westlake program course <关键词>` |
| 通识课程清单（学分/开课学期/教师） | `westlake program courses [--category 理工\|人文\|素质]` |
| 官网全站搜索 | `westlake search <关键词>` |
| 招聘岗位 / 导师名录 | `westlake careers` / `westlake faculty` |
| 校园招聘/招聘会/宣讲会（就业服务网） | `westlake career list [--kind campus|jobfair|teachin]`，网页 `/careers` 下半区 |
| 食堂咖啡 / 公寓 / 电话地址 | `westlake campus dining` / `housing` / `contact phones` |
| 校区地图 / 校园全景 / 怎么到校 | `westlake map [--campus 云谷]` |
| 什么事在哪儿办（全校流程应用目录） | `westlake affairs apps [关键词]` |
| HPC / 预约中心 / 镜像站入口 | `westlake affairs links` |
| 集群队列与节点配置（公开） | `westlake hpc overview`，网页 `/hpc` |
| 报销/财务制度/科研经费文档 | `westlake finance sections/articles`，网页 `/finance` |
| 镜像仓库目录与换源 | `westlake mirrors`，网页 `/mirrors` |
| 全站服务注册表与在线普查 | 网页 `/services`（30 项全接入：方式徽标+扫描按钮） |
| 待办 / 进行中 / 已处理 / 抄送 / 我的应用（办事大厅） | `westlake todo list|doing|done|cc|apps`，网页 `/affairs`（统一密码，请求直登） |
| 门户服务目录（18 部门站点） | `westlake affairs portal`，网页 `/affairs`「门户服务」 |
| 理论科学研究院新闻/学术活动 | `westlake institute news|events`，网页 `/institute` |
| 五学院官网最新新闻（理/生/工/医/理论院） | `westlake schools news <学院>`，网页 `/schools` |
| 服务全景普查（直连子域+办事目录） | `westlake probe scan [--full]`，网页版在 `/capabilities`「运行普查」 |
| 课表/成绩/考试/待评教/第二课堂/导师（网页） | WebUI `/sis`（24 块） |
| Canvas 课程/截止/待办/模块文件（网页） | WebUI `/canvas`；待办 `westlake canvas todo`，模块 `canvas modules <课程>` |
| 招聘岗位（网页） | WebUI `/careers` |
| 打印网点 / 我的打印任务 | `westlake pms stations` / `jobs`，网页 `/pms` |
| 图书馆书目 / 我的借阅 | `westlake lib search <关键词>` / `loans`，网页 `/lib`（OPAC 需校园网/VPN） |
| 学术数据库清单与访问通道 | `westlake scholar dbs [-k 关键词]`，网页 `/scholar` |
| 某篇论文（DOI）的题录/PDF | `westlake scholar doi <doi> [-o out.pdf]`（校园网内走订阅通道直下） |
| 当前 IP 能否直连订阅库 | `westlake scholar campus`（信标探测，缓存 30 分钟） |
| CARSI 联盟资源目录（356 个） | `westlake scholar carsi [关键词] [--refresh]` |
| 校外登录某数据库（CARSI/统一密码） | `westlake scholar ensure`（Agent 主入口：会话活着零动作→验证码关时无头登录→必要时弹浏览器由本人输一次验证码；会话 cookie 全机共享）；`status` 查会话与验证码态 |
| 让别的 Agent 一气呵成用学术资源 | `westlake scholar ensure` 一条命令拿共享会话（~/.westlake_survival/scholar_cookies.json），之后 `scholar doi … -o` 直接带订阅通道下载 |
| 服务是否可达（选课/OPAC/打印/token） | `westlake probe` |
| 这套工具一共能干什么、哪些要账号 | `westlake webui serve` → `/capabilities`（或 `curl /api/capabilities`） |
| 前端接口有哪些、返回什么 | `/capabilities` 页底部「HTTP 接口」区（含实时样例） |
| 一步打开全部功能 | `westlake go`（启动 WebUI 并自动开浏览器，用户唯一要记的命令） |

## 首次使用：用户走网页，终端留给 Agent

用户侧（2026-10-23 裁定：基本不用终端）：

1. 运行一次 `westlake go`（自动启动并打开浏览器；等价 `westlake webui serve` + 手动开页）；
2. 首页横幅或导航「设置」进入 `/setup`，填一次学号 + 密码（可选：Canvas 令牌、地图密码）；
3. 页面当场显示账号是否接通；保存后横幅自动消失。设置页只有一组「学号 + 统一密码」，
   没有任何其它账号输入。

Agent 侧：`westlake setup`（同一套验证与落盘，参数见 --help）。

一次输入的真实边界：教务 SIS 走统一身份认证（IAM OAuth2），填统一（校园门户）
密码即可；Canvas 同一套统一密码（无令牌自动回退 IAM CAS 会话）；打印系统是
另一套密码。公开功能无需任何账号；地图全公开（图片 + 720° 全景）。

## 凭据前提（先判断再执行，缺凭据就换命令）

- **SIS 类**（`sis` / `sis-evals` / `profile` / `records` / `aid` / `lib loans` / `pms jobs`）：需先 `westlake sso creds set` 写入学号密码，且**只在校园网/VPN 内可达**。
- **Canvas 类**（`canvas`）：优先令牌（`WESTLAKE_CANVAS_TOKEN` 或 `~/.westlake_survival/canvas_token.txt` 首行）；**无令牌时自动回退统一认证**（IAM CAS 会话，2026-10-24 实测 REST API 认会话 Cookie）——配好教务统一密码即可用 Canvas，无需任何令牌。
- **电子地图类**：无账号。`/map` 只放官网公开内容（校区地图图片 + 720° 全景链接 + 交通），按用户裁定 2026-10-24 已移除账号与数据集抓取体系。
- **无凭据照常可用**（官网公开数据，校外可直连）：`calendar` / `transit` / `context` / `digest` / `search` / `news` / `program` / `research` / `events` / `careers` / `faculty` / `campus` / `map` / `contact` / `pms stations` / `probe` / `cache`，以及 `scholar dbs|campus|doi|carsi`（学术库注册表、校园 IP 信标、DOI 解析、CARSI 目录——后两者离线也查得到快照，PDF 下载需校园网/VPN 或 OA 副本）。
- **学术资源（2026-10-24 实测）**：本校是 CARSI 联盟成员（`idp.westlake.edu.cn` Shibboleth IdP），统一密码可登录各出版社；校园网内出版社按 IP 认账（ScienceDirect 实测自动认证、Springer PDF 直下实测 200）。`scholar doi` 走「OA 副本（OpenAlex）→ 出版社 citation_pdf_url（校园 IP 订阅通道）」两级取全文；校外先 `scholar sso <库>` 建立联盟会话（Playwright profile 持久化，IAM 若弹图形验证码由本人在窗口输入一次）。
- 快速自检：`westlake sso creds status` 只报四个来源的「有 / 无」，**绝不回显密码**。

## 常用命令速查表

免凭据（可直接执行）：

```bash
westlake calendar today                      # 今日日期/学期/周次/事件
westlake calendar week 4                     # 第 4 周起止日期
westlake calendar events                     # 本学期校历事件
westlake transit next --campus 云谷 --limit 3
westlake transit table --campus 云谷 --day 工作日
westlake transit ical --days 14 --out bus.ics
# 网页订阅：校历页有班车/课表 ICS 一键复制（/ical/shuttle、/ical/schedule）
westlake context --level terse               # terse|normal|verbose
westlake digest --level normal               # 晨报；terse 只留本地快算
westlake search 西湖 --limit 10 --page 1
westlake news --category 学术 --limit 5      # 人物|资讯|学术|校园|招生|媒体|影像
westlake news detail <URL>
westlake program overview                    # 培养目标 + 八项培养特色
westlake program curriculum                  # 课程体系六栏目，含通识课程简表
westlake program majors                      # 8 个专业总览 + 分专业介绍
westlake program majors 临床                 # 按专业名子串过滤
westlake program majors --lang en            # 英文招生网同构（zh 缺省）
westlake program plan                        # 8 专业培养方案：学分块 + 课程表
westlake program plan 人工智能               # 单专业；含先修课程
westlake program plan 人工智能 --detail      # 附每门课的课程简介
westlake program courses                     # 通识课程 99 门（三类）
westlake program courses --category 素质 -k 网球 --detail
westlake program course 机器学习             # 跨源：通识 + 8 专业培养方案
westlake research --limit 10
westlake research detail <URL>
westlake events --days 7 --limit 20 --type 名家讲座
westlake events detail <URL>
westlake careers --category 博士后 --keyword 物理 --limit 20
westlake careers detail <URL>
westlake faculty --school 理学院 --keyword 物理 --limit 20
westlake faculty --source science --limit 20  # --source 可选 all|main|science|sls|teaching，默认 all 聚合四源
westlake faculty detail <URL>                # 仅 /faculty/ 独立主页；--school 可选 理学院|生命科学学院|工学院|医学院
westlake campus dining --campus 云谷 --kind 食堂
westlake campus housing --campus 云谷
westlake contact --campus 云谷               # 云谷|云栖|铜鉴湖；缺省三校区
westlake contact phones
westlake map                                  # 三校区：地址/地图图片/全景/交通
westlake map --campus 云谷
westlake sso creds show                       # 终端显示已存教务学号/密码（忘记 SIS 密码时找回）
westlake vpn login                            # SSL VPN：弹窗手动输验证码，会话落盘复用
westlake vpn status                           # 只报会话有效/失效（不打印令牌）
westlake vpn resources                        # 隧道实际推送的内网主机路由
westlake sites list                           # 37 个站点索引；sites site <key> 看栏目
westlake sites detail <url>                   # 条目详情：正文摘要 / 表格 / 附件
westlake hpc ai                               # Westlake AI 大模型网关（OpenAI 兼容）
westlake pms stations
westlake probe
westlake webui serve --port 2018              # 本地前端；/capabilities 是能力总览
# 前端配色取自西湖大学官网实测（品牌橙 #ee7823 / 门户蓝 #0d5fbd / 门户深墨 #171725 导航）
# + 明暗切换（右上按钮，存 localStorage）+ 弹性缓动动效（spring cubic-bezier）
westlake cache clear --module events
```

需 SIS 凭据 + 校园网/VPN：

```bash
westlake sso creds set                       # 交互输入；--sid/--password/--keyring
westlake sso creds status
westlake sso login                           # 验证凭据是否有效
westlake sis schedule
westlake sis grades
westlake sis exams
westlake sis ical --out schedule.ics
westlake sis-evals list --pending
westlake profile info                        # info|academic|extended
westlake records dorm                        # dorm|leave|honors|volunteer|practice|discipline|second-class|advisor|other-apps
westlake aid loans                           # loans|jobs|outbound|exchange|orgs|activities
westlake lib search 数据结构 --page 1
westlake lib loans
westlake pms jobs
```

需 Canvas 令牌：

```bash
westlake canvas courses
westlake canvas deadlines --limit 10
westlake canvas exams --days 30
westlake canvas assignments --course 概率论        # 列作业（课程给 id 或名称关键词均可）
westlake canvas submit --course 概率论 --assignment 作业3 --file hw3.pdf   # 交作业
westlake canvas submit --course 概率论 --assignment 作业3 --file hw3.pdf --dry-run  # 只预检
westlake canvas submit --course 概率论 --assignment 简介 --text "……"      # 文本提交
westlake canvas submission --course 概率论 --assignment 作业3              # 查提交状态
```

`submit` 是写操作：默认先预检并弹确认，`--yes` 跳过确认，`--dry-run` 只预检不提交；课程/作业都接受 id 或名称关键词（子串匹配，唯一命中才执行；匹配不到就先用 `courses`/`assignments` 查全名——如课程叫「物理学实验 Ⅱ」，搜「物理实验」搜不到；命中多个会列出候选）。提交链路已真机验证（2026-10-15 真交 Lab 5 成功：西湖 Canvas 禁学生写课程文件区，包内自动退回本人文件区上传再提交，效果相同）。

## Python API 直用（需要结构化数据时）

```python
from westlake_survival.context import snapshot, Level
from westlake_survival.transit import transit

print(snapshot(Level.TERSE).to_str())                  # 今日快照纯文本
for table, hhmm in transit().next_departures(limit=3): # 下一批班车
    print(hhmm, table.campus.value)
```

```python
from westlake_survival.sis import get_schedule, grades  # 需凭据 + 校园网

for s in get_schedule():
    print(s.title, s.weekday, s.start_time, s.room)
for g in grades():                                      # 不计算 GPA（无官方换算口径）
    print(g.term, g.course_code, g.course_title, g.grade)
```

```python
from westlake_survival.canvas import canvas                       # 需 Canvas 令牌
from westlake_survival.canvas.models import (SUBMISSION_TYPE_UPLOAD,
    SUBMISSION_TYPE_TEXT, SUBMISSION_TYPE_URL)

c = canvas()
kinds = {SUBMISSION_TYPE_UPLOAD, SUBMISSION_TYPE_TEXT, SUBMISSION_TYPE_URL}
for course in c.list_courses():                                   # 扫描当前可交的作业
    for a in c.list_assignments(course.id):
        if kinds.intersection(a.submission_types) and not a.locked_for_user:
            s = c.get_submission(course.id, a.id)
            print(course.name, a.name, a.due_at,
                  s.workflow_state if s.submitted_at else "未交")
```

## MCP 备选通道

本包自带零依赖 stdio MCP 服务器，暴露 46 个工具（学业 `sis_schedule`/`sis_grades`/`sis_exams`/`sis_evals_pending`/`sis_second_class`/`sis_advisor`/`sis_other_applications` + records/aid 类，校历班车 `calendar_today`/`calendar_week`/`transit_next`，内容 `news_latest`/`events_upcoming`/`research_latest`/`site_search`/`faculty_search`/`affairs_apps`，培养 `program_*` 六个，校园 `campus_dining`/`campus_housing`/`campus_map`/`contact_info`/`context_snapshot`，学术 `scholar_databases`/`scholar_resolve_doi`/`scholar_campus`，作业 `canvas_deadlines`/`canvas_submit`）。客户端配置：

```json
{"mcpServers": {"westlake": {"command": "westlake-mcp"}}}
```

若 `westlake-mcp` 不在 PATH：`"command": "python", "args": ["-m", "westlake_survival.mcp_server"]`。**选型**：要工具自动发现与结构化返回选 MCP；要轻量、零配置、能直接用自然语言描述命令选本 skill。

## Agent 行为守则

- **网络一律直连（2026-10-25 用户裁定，库层已内置）**：用户通常人在校园网但开着系统代理（Clash 等），代理节点没有校园路由——走代理访问 `*.westlake.edu.cn` 会 502/超时。本 skill 所有 HTTP 会话默认 `trust_env=False`（无视 `HTTP_PROXY/HTTPS_PROXY` 直连），**Agent 自己临时写脚本抓校园站点时也必须显式直连**（`requests` 传 `trust_env=False`，或复用 `westlake_survival.discovery.direct_session()`）；唯一例外是 HPC 成果库（172.16.75.35:8007）的代理兜底通道。诊断「校内服务连不上」时先查是否被代理劫持（对照：直连 vs 代理各试一次），再怀疑防火墙/网段 ACL。
- **默认只读，交作业是唯一写操作**：只执行查询/导出命令；`canvas submit`（含 MCP 的 `canvas_submit`）仅凭用户当轮明确给出的课程、作业与文件执行，不尝试选课、抢课、删除等其他写操作，不构造未文档化的请求。
- **交作业三步走**：①预检 `--dry-run`（作业未锁定、类型允许、文件可读）；②提交（用户点名文件即视为授权）；③回读 `canvas submission` 核验（状态 submitted、附件文件名、未迟交）确认后才报完成。已评分（graded）的作业技术上可重交但默认不碰，除非用户明确要求改交。
- **写作业内容先查本地**：动笔前先查 `D:\CanvasMirror` 与 DeepTutor 课程组的本校讲义（与网络通用版有实质差异），实验报告参照本人历史提交物的格式惯例。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不在输出中回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的「有 / 无」。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等属个人隐私，输出给第三方前默认做脱敏/摘要提示，并提醒用户自行确认是否适合分享。
- **失败降级**：`OffCampusError` = 目标系统仅校园网/VPN 可达，提示用户连接 <https://vpn.westlake.edu.cn/>；`AuthError` = 凭据缺失或失效，提示 `westlake sso creds set`；Canvas 报错则提示配置 `WESTLAKE_CANVAS_TOKEN`。命令失败时如实转述错误，不臆造数据。