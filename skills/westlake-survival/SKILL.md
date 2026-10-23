---
name: westlake-survival
description: 查询西湖大学校园信息：课表/成绩/考试/评教、Canvas 作业截止与提交作业、讲座活动、新闻、科研进展、校历周次、班车时刻、食堂公寓、招聘与导师名录、电话地址。用户问及西湖大学（Westlake）课表、成绩、考试、讲座、新闻、校历、班车、教师、食堂等，或要求代交作业/一键晨报/今日快照时使用。
---

# 西湖大学生存手册（westlake-survival）

把西湖大学各服务系统收敛为一条 CLI / 一套 Python API / 一个 MCP 服务器。**默认只读**：本技能只做查询与导出；唯一的写操作是 `canvas submit` 交作业（见下），且仅凭用户当轮明确指令执行，不做选课、抢课等其他写操作。

## 能力地图：哪类问题用哪条命令

| 用户想问 | 命令 |
| --- | --- |
| 今天几号 / 第几周 / 什么学期 / 今日校历 | `westlake calendar today` |
| 本学期第 N 周的起止日期 | `westlake calendar week <N>` |
| 校历事件（开学、假期、考试周） | `westlake calendar events` |
| 下一班校车 / 某校区班车时刻表 | `westlake transit next` / `westlake transit table` |
| 一句话「此刻西湖」（日期+周次+事件+班车+天气） | `westlake context` |
| 每日晨报（快照+活动+班车+周次+Canvas） | `westlake digest` |
| 我的课表 / 成绩 / 考试安排 | `westlake sis schedule` / `grades` / `exams` |
| 待评教任务 | `westlake sis-evals list --pending` |
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
| 食堂咖啡 / 公寓 / 电话地址 | `westlake campus dining` / `housing` / `contact phones` |
| 校区地图 / 校园全景 / 怎么到校 | `westlake map [--campus 云谷]` |
| 打印网点 / 我的打印任务 | `westlake pms stations` / `jobs` |
| 图书馆书目 / 我的借阅 | `westlake lib search <关键词>` / `loans`（OPAC 服务端当前 404，可能不可用） |
| 服务是否可达（选课/OPAC/打印/token） | `westlake probe
westlake webui serve --port 2018              # 本地前端；/capabilities 是能力总览
# 前端外观参考 xiuyuliang.cn：暖纸底 + 白色内容卡 + 细边框 + 明暗切换（右上按钮，存 localStorage）` |
| 这套工具一共能干什么、哪些要账号 | `westlake webui serve` → `/capabilities`（或 `curl /api/capabilities`） |
| 前端接口有哪些、返回什么 | `westlake webui serve` → `/api`（说明页，含实时样例） |

## 首次使用：用户走网页，终端留给 Agent

用户侧（2026-10-23 裁定：基本不用终端）：

1. 运行一次 `westlake webui serve`，浏览器打开 `http://127.0.0.1:2018`；
2. 首页横幅或导航「设置」进入 `/setup`，填一次学号 + 密码（可选：Canvas 令牌、地图密码）；
3. 页面当场显示各服务接通情况；保存后横幅自动消失。

Agent 侧：`westlake setup`（同一套验证与落盘，参数见 --help）。

一次输入的真实边界：教务 SIS 立即接通；Canvas 只认令牌；电子地图密码与教务不同源
（同密码会试一次并如实报告）；打印系统是另一套密码。公开功能无需任何账号。

## 凭据前提（先判断再执行，缺凭据就换命令）

- **SIS 类**（`sis` / `sis-evals` / `profile` / `records` / `aid` / `lib loans` / `pms jobs`）：需先 `westlake sso creds set` 写入学号密码，且**只在校园网/VPN 内可达**。
- **Canvas 类**（`canvas`）：需环境变量 `WESTLAKE_CANVAS_TOKEN`，或写入 `~/.westlake_survival/canvas_token.txt` 首行。
- **电子地图类**：`/map` 页只放官网公开内容（校区地图图片 + 720yun 全景 + 交通），不内嵌第三方地图；楼宇/设施离线查询走**随包数据集**（`westlake map poi`），普通用户无需账号；数据集由维护者用 `tools/capture_map.py` 一次性抓取后 `tools/build_map_dataset.py` 生成。仅当要自己重新抓取时才需要 `westlake map login`（地图系统独立账号，密码与教务不同源，工具按 AES-128-ECB 加密后提交）。
- **无凭据照常可用**（官网公开数据，校外可直连）：`calendar` / `transit` / `context` / `digest` / `search` / `news` / `program` / `research` / `events` / `careers` / `faculty` / `campus` / `map` / `contact` / `pms stations` / `probe` / `cache`。
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
westlake map login                            # 配置电子地图账号（一次，之后自动复用）
westlake map status                           # 只报凭据/令牌有无
westlake map poi 图书馆                        # 离线查楼宇/设施（随包数据集，无需登录）
westlake pms stations
westlake probe
westlake webui serve --port 2018              # 本地前端；/capabilities 是能力总览
# 前端外观参考 xiuyuliang.cn：暖纸底 + 白色内容卡 + 细边框 + 明暗切换（右上按钮，存 localStorage）
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
westlake records dorm                        # dorm|leave|honors|volunteer|practice|discipline
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

本包自带零依赖 stdio MCP 服务器，暴露 18 个工具（`sis_schedule` / `sis_grades` / `sis_exams` / `sis_evals_pending` / `calendar_today` / `calendar_week` / `transit_next` / `news_latest` / `events_upcoming` / `research_latest` / `site_search` / `faculty_search` / `campus_dining` / `campus_housing` / `contact_info` / `context_snapshot` / `canvas_deadlines` / `canvas_submit`）。客户端配置：

```json
{"mcpServers": {"westlake": {"command": "westlake-mcp"}}}
```

若 `westlake-mcp` 不在 PATH：`"command": "python", "args": ["-m", "westlake_survival.mcp_server"]`。**选型**：要工具自动发现与结构化返回选 MCP；要轻量、零配置、能直接用自然语言描述命令选本 skill。

## Agent 行为守则

- **默认只读，交作业是唯一写操作**：只执行查询/导出命令；`canvas submit`（含 MCP 的 `canvas_submit`）仅凭用户当轮明确给出的课程、作业与文件执行，不尝试选课、抢课、删除等其他写操作，不构造未文档化的请求。
- **交作业三步走**：①预检 `--dry-run`（作业未锁定、类型允许、文件可读）；②提交（用户点名文件即视为授权）；③回读 `canvas submission` 核验（状态 submitted、附件文件名、未迟交）确认后才报完成。已评分（graded）的作业技术上可重交但默认不碰，除非用户明确要求改交。
- **写作业内容先查本地**：动笔前先查 `D:\CanvasMirror` 与 DeepTutor 课程组的本校讲义（与网络通用版有实质差异），实验报告参照本人历史提交物的格式惯例。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不在输出中回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的「有 / 无」。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等属个人隐私，输出给第三方前默认做脱敏/摘要提示，并提醒用户自行确认是否适合分享。
- **失败降级**：`OffCampusError` = 目标系统仅校园网/VPN 可达，提示用户连接 <https://vpn.westlake.edu.cn/>；`AuthError` = 凭据缺失或失效，提示 `westlake sso creds set`；Canvas 报错则提示配置 `WESTLAKE_CANVAS_TOKEN`。命令失败时如实转述错误，不臆造数据。