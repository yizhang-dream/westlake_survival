---
name: westlake-survival
description: 查询西湖大学校园信息：课表/成绩/考试/评教、Canvas 作业截止、讲座活动、新闻、科研进展、校历周次、班车时刻、食堂公寓、招聘与导师名录、电话地址。用户问及西湖大学（Westlake）课表、成绩、考试、讲座、新闻、校历、班车、教师、食堂等，或需要一键晨报/今日快照时使用。
---

# 西湖大学生存手册（westlake-survival）

把西湖大学各服务系统收敛为一条 CLI / 一套 Python API / 一个 MCP 服务器。**默认只读**：本技能只做查询与导出，不含选课、抢课、提交类写操作。

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
| 讲座 / 学术会议 / 演出预告 | `westlake events` |
| 西湖新闻 / 科研进展 | `westlake news` / `westlake research` |
| 官网全站搜索 | `westlake search <关键词>` |
| 招聘岗位 / 导师名录 | `westlake careers` / `westlake faculty` |
| 食堂咖啡 / 公寓 / 电话地址 | `westlake campus dining` / `housing` / `contact phones` |
| 打印网点 / 我的打印任务 | `westlake pms stations` / `jobs` |
| 图书馆书目 / 我的借阅 | `westlake lib search <关键词>` / `loans`（OPAC 服务端当前 404，可能不可用） |
| 服务是否可达（选课/OPAC/打印/token） | `westlake probe` |

## 凭据前提（先判断再执行，缺凭据就换命令）

- **SIS 类**（`sis` / `sis-evals` / `profile` / `records` / `aid` / `lib loans` / `pms jobs`）：需先 `westlake sso creds set` 写入学号密码，且**只在校园网/VPN 内可达**。
- **Canvas 类**（`canvas`）：需环境变量 `WESTLAKE_CANVAS_TOKEN`，或写入 `~/.westlake_survival/canvas_token.txt` 首行。
- **无凭据照常可用**（官网公开数据，校外可直连）：`calendar` / `transit` / `context` / `digest` / `search` / `news` / `research` / `events` / `careers` / `faculty` / `campus` / `contact` / `pms stations` / `probe` / `cache`。
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
westlake pms stations
westlake probe
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
```

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

## MCP 备选通道

本包自带零依赖 stdio MCP 服务器，暴露 17 个工具（`sis_schedule` / `sis_grades` / `sis_exams` / `sis_evals_pending` / `calendar_today` / `calendar_week` / `transit_next` / `news_latest` / `events_upcoming` / `research_latest` / `site_search` / `faculty_search` / `campus_dining` / `campus_housing` / `contact_info` / `context_snapshot` / `canvas_deadlines`）。客户端配置：

```json
{"mcpServers": {"westlake": {"command": "westlake-mcp"}}}
```

若 `westlake-mcp` 不在 PATH：`"command": "python", "args": ["-m", "westlake_survival.mcp_server"]`。**选型**：要工具自动发现与结构化返回选 MCP；要轻量、零配置、能直接用自然语言描述命令选本 skill。

## Agent 行为守则

- **只读**：只执行查询/导出命令；不尝试选课、提交、删除等写操作，不构造未文档化的请求。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不在输出中回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的「有 / 无」。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等属个人隐私，输出给第三方前默认做脱敏/摘要提示，并提醒用户自行确认是否适合分享。
- **失败降级**：`OffCampusError` = 目标系统仅校园网/VPN 可达，提示用户连接 <https://vpn.westlake.edu.cn/>；`AuthError` = 凭据缺失或失效，提示 `westlake sso creds set`；Canvas 报错则提示配置 `WESTLAKE_CANVAS_TOKEN`。命令失败时如实转述错误，不臆造数据。