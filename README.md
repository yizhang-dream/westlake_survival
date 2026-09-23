# westlake_survival

在 API 层面调用西湖大学（Westlake University）各服务系统的 Python 模块。它覆盖教务、Canvas、图书馆、自助文印、校巴、校历等日常高频系统，把分散的网页操作收敛成一套统一的 Python / CLI / Web 入口 —— 让脚本和 AI 助手都能直接读校园数据。

架构参考南科大同名项目 [sustech_survival](https://github.com/dumixthestpd/sustech_survival)。**本模块主要由 AI 编写**，欢迎 star、提 issue、加入开发；有问题或想贡献代码，开一个 issue 就能聊起来。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## 免责与许可

- 本项目是**社区项目**，与西湖大学官方**没有任何关系**，不代表学校立场，也未获得官方授权或背书。
- 许可证为 [PolyForm Noncommercial License 1.0.0](./LICENSE)：**仅限非商业用途**，保留署名、禁止商用。
- 西湖大学多数业务系统（SIS / OPAC / 打印等）**只在校园网或学校 VPN 内可达**。校外使用请先连接 VPN：<https://vpn.westlake.edu.cn/>。
- 请**合规使用**：本项目的目的是把「自己本来就能做」的查询和导出自动化。**禁止**用于刷课、抢课、代刷、爬取他人数据、批量注册、绕过权限或其他任何滥用行为。使用本模块产生的后果由使用者自行承担。
- 本项目**按「现状」提供**，不保证可用性：学校系统改版可能导致任意功能随时失效。
- 请自行保护好账号密码与 Canvas 令牌，不要提交进任何仓库。

---

## 模块清单

| 模块 | 服务 | 认证 | 状态 |
| --- | --- | --- | --- |
| `sso` | 统一身份认证（Apereo CAS + PeopleSoft 登录） | 学号 / 密码 | 可用 |
| `sis` | 教务 SIS（PeopleSoft）课表 / 成绩 / 考试 / 评教 / 个人与学籍信息 / 学生记录 / 资助与机会 | `SISAuth` | 可用（成绩 / 考试 / 课表 / 评教 / 信息等已实测） |
| `canvas` | Canvas LMS（课程 / 作业截止 / 文件） | API token | 可用 |
| `lib` | 图书馆 OPAC 检索 / 借阅 | `LibAuth`（检索公开） | 部分可用（OPAC 服务端当前 404） |
| `pms` | 图书馆自助文印（打印 / 扫描 / 账单） | 账号登录 | 可用（36 个方法，接口清单见 `pms/api_notes.md`） |
| `transit` | 校园班车（时刻表 / 下班车 / ics） | 无需 | 可用 |
| `calendar` | 校历（学期 / 周次 / 事件 / 假日） | 无需 | 可用 |
| `ical` | 课表 / 班车 `.ics` 导出 | 视数据源 | 可用 |
| `context` | 每日快照（日期 / 周次 / 天气 / AQI / 班车 / 截止） | 视数据源 | 可用 |
| `mcp_server` | MCP 服务器（stdio，供 AI 客户端接入） | 视数据源 | 可用 |
| `search` | 官网全站搜索（TRS WAS5 搜索接口） | 无需 | 可用 |
| `news` | 西湖新闻（列表 / 详情） | 无需 | 可用 |
| `research` | 科研进展（Research at Westlake，列表 / 详情） | 无需 | 可用 |
| `events` | 活动预告（讲座 / 学术会议 / 演出等，列表 / 详情） | 无需 | 可用 |
| `careers` | 人才招聘（岗位列表 / 详情） | 无需 | 可用 |
| `faculty` | 导师团队（教师名录 / 教师主页） | 无需 | 可用 |
| `campus` | 校园生活（餐饮 / 住宿 / 校园服务） | 无需 | 可用 |
| `contact` | 联系我们（三校区地址 / 交通 / 电话邮箱） | 无需 | 可用 |
| `webui` | 本地 Web 界面（默认 `127.0.0.1:2018`） | 视数据源 | 可用 |
| `cli` | `westlake` 命令行 | 视数据源 | 可用 |

> 上表 `search` / `news` / `research` / `events` / `careers` / `faculty` / `campus` / `contact` 八个官网内容模块的数据源**均为官网公开页面，无需账号、校外可直连**（不涉个人数据，不含凭据）。验证口径：离线解析测试（内置 fixture）+ live 匿名探测（`pytest -m live`，不带任何凭据）；页面改版可能导致解析失败，届时需重新校准。

---

## 安装

需要 **Python >= 3.10**。

依赖（安装时自动拉取）：`requests`、`click`、`beautifulsoup4`、`python-dateutil`、`tzdata`。

本项目**未发布到 PyPI**，从 GitHub 直接安装。仓库地址（yizhang-dream）：

```bash
# 仅 API + CLI
pip install "git+https://github.com/yizhang-dream/westlake_survival.git"

# 加上 Web UI（Flask）
pip install "westlake_survival[webui] @ git+https://github.com/yizhang-dream/westlake_survival.git"

# 加上系统钥匙串（keyring，凭据可存入系统凭据管理器）
pip install "westlake_survival[secure] @ git+https://github.com/yizhang-dream/westlake_survival.git"
```

从源码开发（推荐，`-e` 可编辑安装，改动立即生效）：

```bash
git clone https://github.com/yizhang-dream/westlake_survival.git
cd westlake_survival
python -m venv .venv
# Windows: .venv\Scripts\activate     # macOS / Linux: source .venv/bin/activate
pip install -e ".[webui]"
```

安装完成后验证命令行入口：

```bash
westlake --version
# 或
westlake --help
```

---

## 快速开始

### 1. 配置凭据

凭据按**优先级从高到低**三级解析，任选一种即可：

```python
# 1) 进程内内存（最高优先级，退出即丢失；适合临时脚本）
from westlake_survival import sso
sso.cred_set("20210000", "your-password")
```

```bash
# 2) 环境变量（格式 sid:password）
export WESTLAKE_CREDENTIALS="20210000:your-password"      # Windows PowerShell: $env:WESTLAKE_CREDENTIALS="..."
```

```text
# 3) 配置文件 ~/.westlake_survival/credentials.txt（格式 sid:password）
20210000:your-password
```

命令行方式：

```bash
westlake sso creds set                       # 交互式输入学号 / 密码
westlake sso creds status                    # 查看当前凭据来源与状态
westlake sso login                           # 验证凭据并建立 SIS 会话
```

> Canvas 不走学号密码，而是使用独立的 API token：设置环境变量 `WESTLAKE_CANVAS_TOKEN`，或写入 `~/.westlake_survival/canvas_token.txt`（首行为令牌）。

### 2. 第一个例子：每日快照

```python
from westlake_survival.context import snapshot, Level

print(snapshot(Level.NORMAL).to_str())
```

输出形如：

```text
# 西湖大学 · 2026-09-22 周二 · 2026年秋季 第4周

## 📅 最近校历事件
- 中秋节放假(9月20日补上9月25日的课）（2026-09-25 ~ 2026-09-27）

## 🚌 下班车
- 06:35 从 铜鉴湖 开出
- 06:45 从 云栖 开出
- 07:00 从 铜鉴湖 开出

## 🌤️ 天气
...

## 📌 最近截止
...
```

档位：`Level.TERSE`（纯本地：日期 / 周次 / 学期）、`Level.NORMAL`（默认，加校历事件与班车）、`Level.VERBOSE`（再加天气 / AQI / Canvas 截止）。所有联网项失败都会优雅降级为空，不影响输出。

---

## 各模块用法

### sso — 统一身份认证

认证骨架：`Authorizer` 抽象基类持有每服务一个的单例会话；会话只在内存（TTL 25 分钟，失效自动重登）。子类 `SISAuth` / `LibAuth` / `CanvasAuth` 对应各系统登录。

```python
from westlake_survival import sso

sso.cred_set("20210000", "your-password")     # 也可走环境变量或配置文件
print(sso.cred_path())                        # 配置文件路径
# auth = sso.SISAuth()                        # 每子类单例；auth.ensure() 确保已登录
# session = auth.session                      # 已认证的 requests.Session
```

注意：凭据只在内存与 0600 配置文件里，绝不写日志；`require_auth(SomeAuth)` 装饰器可给函数自动注入已登录实例。

### sis — 教务 SIS（PeopleSoft）

抓取课表 / 成绩 / 考试并解析为数据模型。SIS 走 PeopleSoft 本地表单登录（非 CAS），**需要学号密码**，且**仅在校园网 / VPN 内可达**。

```python
from westlake_survival.sis import get_schedule, ClassSession

for session in get_schedule():                # 仅关键字参数：refresh / source
    print(session.title, session.weekday, session.start_time, session.room)

from westlake_survival.sis import grades, exam_schedule

for g in grades():                            # 全部学期成绩（38 行含历史学期）
    print(g.term, g.course_code, g.course_title, g.grade, g.credits)

for e in exam_schedule():                     # 当前学期考试安排（页头学期由 SIS 决定）
    print(e.course_code, e.date, e.time, e.venue, e.seat)
```

除课表 / 成绩 / 考试外，SIS 还覆盖评教、个人与学籍信息、学生事务记录、资助与机会等组件页，均可从顶层取数：

```python
from westlake_survival.sis import (
    personal_info, academic_record, extended_info,   # 个人信息 / 学籍 / 扩展信息（dict）
    EvalTask, evaluations, pending_evaluations,      # 评教中心
    dormitory, leave_requests, honors,               # 住宿 / 请假 / 荣誉
    volunteer_records, social_practice, discipline_records,
    loans, study_jobs, outbound_programs,            # 资助 / 勤工 / 交流
    exchange_applications, exchange_schools,
    student_orgs, my_clubs, student_activities,      # 社团
)

print(personal_info())                       # {"字段标签": "值", ...}
print(len(pending_evaluations()))            # 待评任务数
print(dormitory().info)                      # 宿舍信息字典
for loan in loans():
    print(loan.loan_type, loan.amount, loan.status)
```

命令行：

| 命令 | 说明 |
| --- | --- |
| `westlake sis schedule` / `grades` / `exams` / `ical` | 课表 / 成绩 / 考试安排 / 课表 `.ics` 导出 |
| `westlake sis-evals list [--pending]` | 评教中心：全部评估任务；`--pending` 只看未完成 |
| `westlake profile info` / `academic` / `extended` | 个人信息 / 学籍数据 / 扩展信息（含紧急联系人等网格） |
| `westlake records dorm` / `leave` / `honors` / `volunteer` / `practice` / `discipline` | 住宿 · 请假 · 荣誉 · 志愿 · 社会实践 · 违纪 |
| `westlake aid loans` / `jobs` / `outbound` / `exchange` / `orgs` / `activities` | 贷款 · 勤工助学 · 海外交流（派出 / 交换）· 社团组织与活动 |

口径（诚实说明，均为 2026-09-23 登录态实测）：

- **评教**：评教中心真页实测 25 行，`Evaluation Status` **全部为 `Submit`**，站点未提供状态图例；`COMPLETED_STATUSES` 为可覆盖的保守「已完成」口径，当前无一条被判为已完成，故 `--pending` 返回全部 25 条待评。`detail_url` 恒为空串（真页 Detail 是 JS 按钮，无真实 URL）。
- **考试**：当前学期考试页部分字段（日期 / 时间 / 类型 / 方式 / 考场 / 座位）**暂未排期**，页面返回空字段，命令如实以 `—` 显示，不臆造。
- **空数据页如实说**：贷款 / 勤工助学 / 交流申请 / 社团活动等页面对当前账号为空，取数函数返回空列表、命令打印「没有…记录」等占位提示（不报错、不造数）。
- **个人信息 / 学籍 / 扩展信息**返回「字典 + 键名清单」而非 dataclass——字段集合由学校 PeopleSoft 配置决定、会随配置漂移，调用方按需 `.get(key)`。

注意：`ClassSession` 描述「一次上课节次」（同一门课一周两次就是两条）。成绩 / 考试 / 评教 / 信息等组件页走共享读取层 `sis/pages.py`（登录态抓页 + fluid 网格解析；门户索引 `CSPRD_x` 是**会话态**、动态解析，勿写死）。登录、课表页（`SSR_VW_CLASS_FL` fluid 网格）、成绩页（`WL_STU_ENRL_V2`）、考试页（`WL_EXAM_STU_VW`）、评教页（`WL_STU_EVAL_CEN` / `WL_EVAL_WRK`）、两段式导出链路已于 2026-09-23 用真实账号实测校准（页面解析与导出文件逐字段一致）；PeopleSoft 页面结构若变动，可能需要重新校准解析器。`grades()` 不计算 GPA——成绩含等级制与未出分，缺官方换算口径时任何加权平均都是臆造。

### canvas — Canvas LMS

基于 Canvas 自带 REST API，Bearer Token 认证，不依赖 sso。

```python
from westlake_survival.canvas import canvas

client = canvas()                             # 单例工厂，token 自动解析
print(client.me().name)                       # 当前用户
for course in client.list_courses():
    print(course.name)
for assignment in client.upcoming_deadlines(5):
    print(assignment.due_at, assignment.name)
for exam in client.exams(days=30):            # 测验型作业 ∪ 课程日历事件，按时间升序
    print(exam.kind, exam.title)
```

命令行：`westlake canvas exams [--days N]` 输出考试安排表（缺省不过滤时间窗口）。

令牌生成路径：Canvas 网页 →「账户」→「设置」→「新建访问令牌」（是否开放由管理员控制）。任选一种提供：`WESTLAKE_CANVAS_TOKEN` 环境变量，或 `~/.westlake_survival/canvas_token.txt` 首行。

### lib — 图书馆 OPAC

书目检索（公开）、新书推荐，以及需登录的个人借阅。

```python
from westlake_survival.lib import search, book_detail, my_loans

for book in search("机器学习", kind="title"):  # kind: title/author/isbn/keyword…
    print(book.title, book.call_no, book.location)

# 借阅需先完成 SSO 登录（LibAuth）
for loan in my_loans():
    print(loan.title, loan.due_date)
```

注意：**OPAC 检索端点（`/opac/booklist.jsp`）服务端当前返回 404**，故 `search` / `new_books` 可能抛 `ParseError`；此时可尝试门户 JSON 路线 `search_catalog()`（需已登录会话）。个人借阅页路径同样待有账号后校准。

### pms — 图书馆自助文印

面向图书馆自助打印控制器（联创 UniOpm 云打印）。凭据登录时按需从 sso 读取。

```python
from westlake_survival.pms import pms

client = pms()                                # 单例；也可 pms(username=..., password=...)
client.list_stations()                        # 网点列表（无需登录）
client.login()                                # 登录
client.list_print_jobs()                      # 我的打印任务
client.upload("hw.pdf", copies=2)             # 上传并创建打印任务
client.usage_stat()                           # 累计用量
```

警告：`recharge()` / `get_bill()` 等支付相关方法**会真实影响一卡通余额**，调用前务必读其 docstring；本库不做金额校验与二次确认。完整端点清单见 `src/westlake_survival/pms/api_notes.md`。

### transit — 校园班车

时刻表数据来自官网页面内嵌 JS，网络不可达时回退内置兜底数据。

```python
from westlake_survival.transit import transit, Campus, DayKind

data = transit()                              # 惰性加载 + 缓存
print(data.table(Campus.YUNGU, DayKind.WEEKDAY).all_times())
for table, clock in data.next_departures(campus=Campus.YUNGU, limit=3):
    print(clock, "从", table.campus.value, "开出")
```

注意：`morning` / `noon` / `night` 只是官网时段分组名，**时刻都是从本表校区开出**，方向见 `direction_note`；日别仅按公历星期推断，**不含法定假期 / 调休**，假期班车以学校邮件通知为准。

### calendar — 校历

把校历变成可编程查询对象：给定日期查学期、教学周、是否假日 / 教学日、最近事件。网络失败时用内置常量兜底。

```python
from datetime import date
from westlake_survival.calendar import load

cal = load()                                  # 等价于 AcademicCalendar.load()
semester = cal.current()                      # 当前学期
print(semester.name, semester.teaching_weeks())
print(cal.week_of(date.today()))              # (学期, 教学周)
print(semester.is_holiday(date(2026, 10, 1))) # 是否假日
print(cal.next_event().title)                 # 最近事件
```

注意：无认证、仅抓校历主页；数据更新有滞后，抓不到时以内置 `FALLBACK_DATA` 兜底。

### ical — `.ics` 导出

把课表 / 班车导出为标准 iCalendar 文本，可直接导入日历。

```python
from westlake_survival.ical import courses_to_ical, save_ics
from westlake_survival.sis import get_schedule

sessions = get_schedule()                     # 需要 SIS 凭据
text = courses_to_ical(sessions)              # 直接拿 .ics 字符串
save_ics(sessions, "schedule.ics")            # 或直接写文件（返回 Path）

# 班车自身也提供导出函数
from westlake_survival.transit import transit_to_ical
open("shuttle.ics", "w", encoding="utf-8").write(transit_to_ical())
```

注意：班车 `.ics` 用浮动本地时间，日别仅按星期推断，不含法定假期 / 调休；课表导出的字符集检查依赖 SIS 数据源。

### context — 每日快照

面向 AI 助手 / 学生的「此刻西湖」入口，输出 markdown 文本或 JSON 可序列化 dict。

```python
from westlake_survival.context import Context, Level, snapshot

snapshot(Level.NORMAL).to_str()               # 中文 markdown 快照
snapshot(Level.TERSE).to_dict()               # JSON 可序列化 dict
snapshot(Level.VERBOSE)                       # + 天气 + AQI + Canvas 截止
```

注意：所有 I/O 失败都降级为 `None`，构造与序列化绝不抛异常，适合直接塞给 LLM。

### search — 官网全站搜索

检索西湖大学官网全部内容（新闻、活动、招聘、页面等），数据源是官网公开的 TRS WAS5 全站搜索 JSON 接口，**无需账号、校外可直连**。

```python
from westlake_survival.search import search

result = search("西湖", page=1)               # 第 1 页，每页约 10 条
print(result.total, result.page_count)        # 命中总数 / 可翻页数
for hit in result.hits:
    print(hit.date, hit.clean_title, hit.url) # clean_title 已剥掉高亮 <font> 标签
```

注意：响应头是 `text/html;charset=UTF-8` 但 `requests` 会误判为 latin-1，库内一律按 `response.content` 手动 UTF-8 解码；命中关键词在标题里被 `<font>` 包裹，`clean_title` / `clean_desc` 给出纯文本。

### news — 西湖新闻

抓取官网「西湖新闻」列表与详情，**无需账号、校外可直连**。

```python
from westlake_survival.news import latest, fetch_detail

for item in latest(limit=10):                 # 最新在前；可按 category 过滤
    print(item.date, item.category, item.title)

detail = fetch_detail(item.url)               # 详情页（不缓存）
print(detail.title, detail.author, detail.content_html)
```

注意字段陷阱：列表原始条目的 `title` 是**分类**、`content` 才是**标题**，本模块已在 `NewsItem` 层映射为语义正确的 `title` / `category`。列表页走 ETag 条件 GET + 本地缓存。

### research — 科研进展

抓取官网「科研进展」（Research at Westlake）列表与详情，**无需账号、校外可直连**。列表页 `researchWestlake` 组件按研究方向分组，约 32 条（分 7 个方向）。

```python
from westlake_survival.research import latest, fetch_detail, CATEGORIES

for item in latest(limit=10):                 # 按官网分组顺序展平；可按 category 过滤
    print(item.date, item.category, item.title)

detail = fetch_detail(item.url)               # 详情页（不缓存）
print(detail.title, detail.author, detail.content_html)
```

命令行：`westlake research [--category X] [--limit N]`、`westlake research detail <url>`。

注意字段陷阱：列表条目只有 `abs` 一个文本字段（既作标题又作摘要），本模块在 `ResearchItem` 层把 `abs` 映射为 `title` / `summary`、把分组 `title` 映射为 `category`。**条目本身没有日期字段**，唯一可靠的发布时间编码在详情页 URL 的 `tYYYYMMDD_` 片段里，本模块用 `parse_url_date` 从中推断 `date`（URL 不含该片段时为 `None`，不臆造）。列表页走 ETag 条件 GET + 本地缓存。

### events — 活动预告

抓取官网「活动预告」（讲座 / 学术会议 / 演出等），**无需账号、校外可直连**。

```python
from westlake_survival.events import upcoming, load_events, fetch_detail

for item in upcoming(days=14):                # 未来 14 天，按开始时间升序
    print(item.date, item.event_type, item.title, item.venue)

for item in load_events(event_type="名家讲座", since=..., limit=20):
    print(item.title, item.organizer)

detail = fetch_detail(item.url)               # 详情页
print(detail.title, detail.host, detail.content_html)
```

注意：列表页的 `eventList` 是**全量**数组（含历史活动），故 `since` / `until` / `days` 是常用收窄手段；列表页走 ETag 条件 GET + 本地缓存，详情页每次直连不缓存。

### careers — 人才招聘

抓取学校招聘主页的岗位列表与详情，**无需账号、校外可直连**。

```python
from westlake_survival.careers import positions, fetch_detail

for p in positions(category="博士后", keyword="生命", limit=20):
    print(p.title, p.department, p.location, p.apply_url)

detail = fetch_detail(p.url)                  # 外部平台链接则直接返回外链
print(detail.title, detail.content_html)
```

注意：官网把**岗位标题**放在 `dept` 字段、`type` 字段用中英文逗号分隔「性质 / 部门 / 地点」（地点本身含中文逗号，按逗号最多切两刀）；`url2` 非空时指向外部招聘平台（如 `app.mokahr.com`），`fetch_detail` 对外链不做解析。

### faculty — 导师团队

查询西湖大学教师名录与教师主页，**无需账号、校外可直连**。

`members()` **默认聚合四个公开数据源**（约 335 人），按 `url` 去重、主站优先：

| `source` | 数据源 | 人数（2026-09-24 实测） |
| --- | --- | --- |
| `main` | 主站「导师团队」名录 `about/faculty/` | 302 |
| `science` | 理学院教师列表接口（POST JSON） | 125 条，净增约 10 |
| `sls` | 生命科学学院 `Our_Faculty/json_401.json` | 118 条，净增约 2 |
| `teaching` | 通识课授课教师页 | 28 人，净增约 22 |

官网 `about/faculty/` 的 `memberList` 只是「导师团队」名录、**并非全校教师全集**：理学院、生科院与通识课授课教师页另有收录（如曹趣、王子桐、方睿、肖宇晨及多数授课教师）。任一子源失败只降级跳过并记 warning，其余源照常返回。

```python
from westlake_survival.faculty import members, fetch_detail

for m in members(school="理学院", keyword="物理", limit=20):
    print(m.name, m.school, m.subject, m.lab or "—", m.source, m.work_type or "", m.url)

members(source="science", limit=10)            # 只取理学院源
members(source="teaching")                     # 只取通识课授课教师

detail = fetch_detail(m.url)                  # 仅支持 /faculty/ 独立主页
print(detail.title, detail.email, detail.research_html)
```

注意：`subject` 字段用 `</br>` 把「首学科」与「实验室/方向」拼在一起，本模块拆成 `subject` 与 `lab`；`school` 按**子串**匹配，兼聘教师会在其各学院下都出现（授课教师的 `school` 为「通识课程」）；`source` 标识来源（`main`/`science`/`sls`/`teaching`），`work_type` 只在理学院源有值（主聘/兼聘/教学/访问）。`fetch_detail()` **只支持 `/faculty/` 独立主页**：授课教师 / 无独立主页的条目调用时抛 `ParseError` 并说明「该教师无独立主页」。主站与授课教师页走 ETag 条件 GET，理学院接口无 ETag 改为 JSON 缓存（失败时回退缓存体）。

### campus — 校园生活（餐饮住宿）

抓取官网「校园生活 / 餐饮住宿」页面：食堂、咖啡轻食、公寓与校园服务，**无需账号、校外可直连**。

```python
from westlake_survival.campus import dining, housing, services

for spot in dining(kind="食堂", campus="云谷"):
    print(spot.name, spot.address, "；".join(spot.hours))

for house in housing(campus="云栖"):
    print(house.name, house.address, house.phone)
```

注意：班车「交通方式」部分由 `transit` 模块覆盖，本模块只把班车实时信息外链抽成常量 `SHUTTLE_LIVE_URL`；餐饮 / 住宿 / 服务的营业时间与服务信息均从页面 HTML 换行标记逐行拆成纯文本；页面走 ETag 条件 GET + 进程内单例缓存（`load(refresh=True)` 强制重取）。

### contact — 联系我们

查询三校区地址、邮编、交通方式、校区地图，以及常用电话邮箱，**无需账号、校外可直连**。

```python
from westlake_survival.contact import campuses, contacts, GENERAL_CONTACTS

for info in campuses():
    print(info.name, info.address, info.postcode, info.map_url)
    for line in info.traffic:
        print(" -", line)

for entry in contacts():
    print(entry.label, entry.phones, entry.emails)
```

注意：页面 `/about/` 目录本身返回 403，必须带完整子路径 `/about/contact_us/`；三校区依次为云谷、云栖、铜鉴湖（页面写作「云栖校区（铜鉴湖园区）」，本模块归一化），铜鉴湖园区没有地图；页脚公共事务部总机 / 媒体邮箱 / 传真硬编码在 `GENERAL_CONTACTS` 常量。

### webui — 本地 Web 界面

```python
from westlake_survival.webui import create_app, run

app = create_app()                            # WSGI app，便于自挂服务器
run(port=2018)                                # 启动内置服务器（默认 127.0.0.1:2018）
```

注意：需安装 `webui` extra（Flask）；默认只监听回环地址 `127.0.0.1:2018`，数据可见性与已配置的凭据一致。启动走 CLI 子命令 `westlake webui serve`（见下节）或 `python examples/webui_demo.py`。

### cli — `westlake` 命令行

见下一节。

---

## CLI 用法

安装后提供 `westlake` 命令。命令树如下（`westlake --help`）：

```text
westlake
├── sso
│   ├── creds
│   │   ├── set            # 设置 / 写入凭据
│   │   └── status         # 查看当前凭据状态
│   └── login              # 验证凭据并建立 SIS 会话
├── calendar
│   ├── today              # 今日快照（日期 / 周次 / 事件）
│   ├── events             # 校历事件列表
│   └── week               # 当前 / 指定教学周
├── transit
│   ├── next               # 下一班车
│   ├── table              # 时刻表
│   └── ical               # 导出班车 .ics
├── canvas
│   ├── courses            # 我的课程
│   ├── deadlines          # 即将到期的作业
│   └── exams              # 测验与考试事件
├── sis
│   ├── schedule           # 本学期课表
│   ├── grades             # 全部学期成绩
│   ├── exams              # 当前学期考试安排
│   └── ical               # 导出课表 .ics
├── sis-evals
│   └── list [--pending]   # 评教任务（--pending 只看未完成）
├── profile
│   ├── info               # 个人信息
│   ├── academic           # 学籍数据
│   └── extended           # 扩展信息（紧急联系人等网格）
├── records
│   ├── dorm               # 住宿申请与宿舍信息
│   ├── leave              # 请假申请
│   ├── honors             # 荣誉记录
│   ├── volunteer          # 志愿服务
│   ├── practice           # 社会实践
│   └── discipline         # 违纪信息
├── aid
│   ├── loans              # 贷款记录
│   ├── jobs               # 勤工助学
│   ├── outbound           # 海外交流（派出）
│   ├── exchange           # 交换生申请
│   ├── orgs               # 学生组织 / 社团目录
│   └── activities         # 社团活动登记
├── lib
│   ├── search             # 书目检索
│   └── loans              # 我的借阅
├── pms
│   ├── stations           # 打印网点
│   └── jobs               # 我的打印 / 扫描任务
├── search <关键词>        # 官网全站搜索（--page / --limit）
├── news                   # 西湖新闻（--category / --limit）
│   └── detail <url>       # 新闻详情
├── research               # 科研进展（--category / --limit）
│   └── detail <url>       # 科研进展详情
├── events                 # 活动预告（--type / --days / --limit）
│   └── detail <url>       # 活动详情
├── careers                # 人才招聘（--category / --keyword / --limit）
│   └── detail <url>       # 岗位详情
├── faculty                # 导师团队（--school / --keyword / --source / --limit / --all）
│   └── detail <url>       # 教师主页（仅 /faculty/ 独立主页）
├── campus
│   ├── dining             # 食堂 / 咖啡轻食（--campus / --kind）
│   └── housing            # 公寓（--campus）
├── contact                # 三校区地址 / 交通 / 地图（--campus）
│   └── phones             # 常用电话与邮箱
├── context [--level]      # 每日快照（terse / normal / verbose）
├── digest [--level]       # 晨报一条龙（terse / normal）
├── probe                  # 堵点状态探测（SIS 选课 / OPAC / 打印 / Canvas token）
├── cache
│   └── clear [--module]   # 清除本地缓存（前缀匹配某个模块，缺省全部）
└── webui
    └── serve [--port]     # 启动 Web UI
```

示例：

```bash
westlake context --level normal
westlake digest                       # 晨报：快照 + 活动 + 班车 + 周次 + Canvas 截止
westlake digest --level terse         # 只保留本地快算与周次
westlake probe                        # 探堵点：选课是否开放 / OPAC 是否恢复 / 打印可达 / token
westlake cache clear                  # 清空全部本地缓存
westlake cache clear --module events  # 只清活动预告缓存
westlake transit next
westlake calendar today
westlake canvas deadlines
westlake search 西湖 --limit 2
westlake news --category 学术 --limit 5
westlake research --limit 10
westlake sis grades
westlake sis exams
westlake sis-evals list --pending
westlake profile academic
westlake records dorm
westlake aid loans
westlake events --days 3
westlake careers --category 博士后 --limit 10
westlake faculty --school 理学院 --keyword 物理
westlake faculty --source science --limit 10   # 只取理学院源（all|main|science|sls|teaching）
westlake campus dining
westlake contact phones
```

### 晨报：`westlake digest`

把**上下文快照 + 今日/明日活动 + 下一班校车 + 本周次**（可选 Canvas 截止）合成一段可直接推送的中文文本，适合定时任务 / 机器人推送 / 每日开工第一屏：

```bash
westlake digest                 # 默认 normal 档：全部数据源
westlake digest --level terse   # 只保留本地快算（日期 / 周次 / 学期）与本周次
```

输出形如：

```text
# 西湖大学晨报 · 2026-09-23 周三

## 概览
- 2026-09-23 · 周三 · 2026年秋季 · 第4周

## 今日 / 明日活动
- 09-23 14:00 西湖理学讲坛| 程金光：稀土Eu掺杂无限层镍基超导薄膜的反常物性研究（云谷校区E10-211）

## 下一班校车
- 19:30 从 铜鉴湖 开出
- 19:35 从 铜鉴湖 开出
- 19:45 从 云谷 开出

## 本周次
- 学期：2026年秋季
- 本周：第 4 周（共 17 周）

## Canvas 截止
（未配置 WESTLAKE_CANVAS_TOKEN，跳过 Canvas 截止）
```

**降级语义**：每个数据源独立 `try/except`，任一源失败只把该节降级为占位行（并附异常类名），不影响其余各节，整条命令始终退出码 0。Canvas 截止**仅当**配置了 `WESTLAKE_CANVAS_TOKEN`（或 token 文件）时才并入；未配置时跳过并说明，不报错。

### 堵点探测：`westlake probe`

一次性探测几个「卡点」的当前状态（全部只读 GET，逐项 8 秒超时，输出表格）：

```bash
westlake probe
```

```text
探测项            状态          说明
----------------  ------------  ----------------------------------------------------------
SIS 选课组件授权  选课窗口未开  组件未授权（正文含 not authorized）
OPAC 端点         HTTP 404      仍未恢复（服务端 404）
打印系统匿名接口  可达          匿名可读，4 个网点
Canvas token      未配置        设置环境变量 WESTLAKE_CANVAS_TOKEN 或写入 canvas_token.txt
```

- **SIS 选课组件授权**：登录态 GET `SSR_STUDENT_FL.SSR_SHOP_CART_FL.GBL`；正文含 `not authorized` → 「选课窗口未开」，否则「已授权（可开发选课功能！）」。其余异常（校外 / 未登录）显示为「失败」并附原因。
- **OPAC**：GET `http://172.16.10.223:8180/opac/`；`404` → 「仍未恢复」。
- **打印系统匿名接口**：GET `/api/client/Station/GetList`，匿名可达时报告网点数。
- **Canvas token**：是否已配置（环境变量或 token 文件）。

每项失败只让该行显示为「失败」，**不炸整表**、命令始终退出码 0。

### 缓存管理：`westlake cache clear`

各官网内容模块（校历 / 班车 / 活动预告等）用 ETag 条件请求把响应体缓存到 `~/.westlake_survival/cache/`。页面改版或想强制拉新时清掉缓存即可：

```bash
westlake cache clear                  # 清空全部缓存，回报清除文件数
westlake cache clear --module events  # 只清活动预告（按路径前缀匹配）
westlake cache clear --module transit # 只清班车时刻表
```

`--module` 是相对缓存目录的**路径前缀**（如 `events`、`transit`、`calendar`，也可给到具体文件名）；缺省清空整个缓存目录。清不掉的单个文件（被占用等）会跳过并继续，不报错。

---

## Web UI

启动方式（三选一）：

```bash
westlake webui serve                # 默认端口
westlake webui serve --port 8080    # 指定端口
python examples/webui_demo.py       # 示例脚本
```

启动后浏览器访问 <http://127.0.0.1:2018/>（或你指定的端口）。默认端口 **2018**，仅监听回环地址 `127.0.0.1`；如需局域网访问请自行配置反向代理。

页面：`/`（仪表盘）、`/shuttle`（班车）、`/calendar`（校历）、`/events`（讲座活动：官网活动预告 + 西湖新闻，数据源失败时对应区块优雅隐藏、页面仍 200）。

---

## 作为 Agent Skill / MCP 接入

本包可把校园数据接入 AI Agent，有**两条通道**，任选其一或并用：

### 通道一：Agent Skill（轻量、零配置）

仓库内 [`skills/westlake-survival/SKILL.md`](skills/westlake-survival/SKILL.md) 是一份写给 Agent 的技能说明（能力地图 / 命令速查 / 凭据前提 / 行为守则）。安装方式即「复制目录」：

```bash
# ZCode / Claude Code 系：复制到用户级 skills 目录
mkdir -p ~/.zcode/skills
cp -r skills/westlake-survival ~/.zcode/skills/

# 或放到项目级 skills 目录（仅该项目可见）
cp -r skills/westlake-survival <your-project>/skills/
```

Claude 系客户端（Claude Code / Claude Desktop 的技能目录）同理，把 `westlake-survival/` 整个目录放进其 skills 目录即可。安装后 Agent 会在用户问及西湖大学课表 / 成绩 / 讲座 / 校历 / 班车等时自动加载该技能，并按其中命令调用 `westlake` CLI。

### 通道二：MCP 服务器（工具化、结构化）

内置零依赖 stdio MCP 服务器，暴露 17 个工具（课表 / 成绩 / 考试 / 评教 / 校历 / 班车 / 新闻 / 活动 / 科研 / 搜索 / 导师 / 餐饮 / 公寓 / 联系 / 快照 / Canvas 截止）。配置示例：

```json
{
  "mcpServers": {
    "westlake": {
      "command": "westlake-mcp"
    }
  }
}
```

`westlake-mcp` 不在 PATH 时改用解释器模块方式：

```json
{
  "mcpServers": {
    "westlake": {
      "command": "python",
      "args": ["-m", "westlake_survival.mcp_server"]
    }
  }
}
```

### 两通道选型建议

| 需求 | 选 |
| --- | --- |
| 要工具**自动发现**、参数校验、结构化 JSON 返回，Agent 自主编排多步查询 | **MCP** |
| 要**轻量零配置**、不装额外服务，Agent 直接用自然语言描述的命令（也可跑 `--help` 自查） | **Skill** |
| 两者都要 | 同时安装：MCP 供工具调用，Skill 供行为守则与能力地图 |

两条通道共用同一份数据层与凭据配置（SIS 走 `westlake sso creds set`，Canvas 走 `WESTLAKE_CANVAS_TOKEN`），也共用「只读、不打印凭据、个人数据脱敏、`OffCampusError` 提示连 VPN」的行为约定。

---

## MCP 接入

项目内置一个 MCP（Model Context Protocol）服务器，走 **stdio** 传输，把校园数据直接暴露给 AI 客户端（Claude Desktop / ZCode / Cline 等）。安装后即提供 `westlake-mcp` 命令，也可用模块方式启动：

```bash
pip install -e ".[secure]"    # secure extra 提供 keyring（可选，见下节）
```

客户端配置示例（`command` 二选一）：

```json
{
  "mcpServers": {
    "westlake": {
      "command": "westlake-mcp"
    }
  }
}
```

若 `westlake-mcp` 不在 PATH 中，改用解释器模块方式：

```json
{
  "mcpServers": {
    "westlake": {
      "command": "python",
      "args": ["-m", "westlake_survival.mcp_server"]
    }
  }
}
```

在 Windows 虚拟环境下，建议 `command` 指向虚拟环境的解释器绝对路径（如 `D:/path/to/.venv/Scripts/python.exe`），`args` 为 `["-m", "westlake_survival.mcp_server"]`，避免 PATH 歧义。

---

## 凭据安全

凭据（学号 / 密码）与 Canvas 令牌**绝不写日志、绝不随会话落盘**；除明文配置文件外，还支持把凭据存入**系统钥匙串（keyring）**：

```bash
pip install -e ".[secure]"        # 安装 keyring>=25（可选依赖）
westlake sso creds set --keyring  # 显式写入系统钥匙串
westlake sso creds set            # 缺省：keyring 可用时优先写钥匙串并提示
westlake sso creds set --no-keyring  # 强制走原明文文件路径
westlake sso creds status         # 显示四来源：内存 / 环境变量 / keyring / 文件
```

**凭据来源优先级**（与 `read_credentials` 一致，从高到低）：

1. 进程内存（`sso.cred_set`，退出即失）；
2. 环境变量 `WESTLAKE_CREDENTIALS`（格式 `sid:password`）；
3. 系统钥匙串 keyring（需 `[secure]` extra）；
4. 明文配置文件 `~/.westlake_survival/credentials.txt`（写盘时尽力设为 `0600`，Windows 权限语义有限）。

**迁移提示**：已经用明文文件存过凭据的用户，可执行 `westlake sso creds set --keyring` 把凭据改存钥匙串，随后删除 `~/.westlake_survival/credentials.txt`（删除文件不在本项目职责内，请自行确认）。`sso creds status` 会列出四个来源各自的「有 / 无」，便于确认迁移是否到位；keyring 不可用时（未装 `[secure]`）自动降级为原有的三级来源行为，不影响使用。

---

## 开发

```bash
python -m venv .venv
.venv/Scripts/activate             # Windows（macOS / Linux: source .venv/bin/activate）
pip install -e ".[webui]"
python -m pytest src/test/ -v      # 单元测试（离线、mock，默认排除 live）
python -m pytest src/test/ -m live # 联网测试：需校园网与有效凭据
```

测试通过 pytest marker `live` 区分：默认 `-m 'not live'` 只跑离线用例；`-m live` 才跑需要校园网 / 账号的探测。

目录结构：

```text
westlake_survival/
├── src/westlake_survival/
│   ├── sso/          # 统一身份认证骨架 + 各服务登录
│   ├── sis/          # 教务 SIS（PeopleSoft）
│   ├── canvas/       # Canvas LMS
│   ├── lib/          # 图书馆 OPAC
│   ├── pms/          # 自助文印（含 api_notes.md）
│   ├── transit/      # 校园班车 + ical
│   ├── calendar.py   # 校历
│   ├── ical/         # 通用 .ics 导出
│   ├── context/      # 每日快照
│   ├── search.py     # 官网全站搜索
│   ├── news.py       # 西湖新闻
│   ├── research.py   # 科研进展（Research at Westlake）
│   ├── events.py     # 活动预告
│   ├── careers.py    # 人才招聘
│   ├── faculty.py    # 导师团队
│   ├── campus.py     # 校园生活（餐饮住宿）
│   ├── contact.py    # 联系我们
│   ├── webui/        # 本地 Web 界面
│   ├── cli/          # westlake 命令行
│   ├── exceptions.py # 统一异常体系
│   └── _cache.py / _net.py
├── src/test/         # 测试（离线 + live）
├── examples/         # 可独立运行的小脚本
└── pyproject.toml
```

致谢：[sustech_survival](https://github.com/dumixthestpd/sustech_survival)（架构参考）与 westlake-ics（校历 / 课表数据探索）。

`sis` 模块的西湖大学 13 节排课时间表（`PERIOD_SCHEDULE`）移植自 [westlake-ics](https://github.com/wzsyyh/westlake-ics) 的 `ps2wakeup.py` 及其 README 中的官方节次对照表；该上游仓库未附 LICENSE（截至 2026-09-22 未见授权声明），此处仅移植**事实性排课时间数据**并注明来源。详见 `src/westlake_survival/sis/parser.py` 的常量注释。

---

## 常见问题

**输出中文乱码？**
Windows 控制台默认编码（GBK / cp936）可能无法显示中文。建议：

```bash
set PYTHONUTF8=1            # 或 export PYTHONUTF8=1
chcp 65001                  # 切到 UTF-8 代码页
```

或改用 Windows Terminal / PowerShell 7 并设置 UTF-8 输出。

**请求返回 403 / 无法访问？**
说明你在校外。多数系统仅校园网 / VPN 内可达，请先连接西湖大学 VPN：<https://vpn.westlake.edu.cn/>。库遇到校外阻断会抛 `OffCampusError`。

**凭据存放是否安全？**
凭据只在四处出现：进程内存（`cred_set`，退出即失）、环境变量、系统钥匙串 keyring（需 `[secure]` extra）、`~/.westlake_survival/credentials.txt`（写盘时尽力设为 `0600`，Windows 权限语义有限）。库**绝不写日志、绝不随会话落盘**。推荐用 `westlake sso creds set --keyring` 把凭据存入系统钥匙串（安全性高于明文文件），`westlake sso creds status` 可查看四来源。Canvas 令牌同理，存放在 `WESTLAKE_CANVAS_TOKEN` 或 `~/.westlake_survival/canvas_token.txt`。

**OPAC 检索报 `ParseError`？**
图书馆 OPAC 检索端点服务端当前返回 404（已知现状），可尝试门户 JSON 路线 `search_catalog()`（需登录）。

**SIS 抓不到课表？**
SIS 走 PeopleSoft 表单登录，需学号密码且在校园网 / VPN 内；若学校更新了页面结构，解析器可能需要重新校准。

---

## 相关项目

- [sustech_survival](https://github.com/dumixthestpd/sustech_survival) — 本项目架构的参考来源（南方科技大学同名项目）。

## 许可

[PolyForm Noncommercial License 1.0.0](./LICENSE) —— 仅限非商业用途，保留署名。
