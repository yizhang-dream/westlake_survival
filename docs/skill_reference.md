# skill_reference —— SKILL.md 的细节下放层

> SKILL.md 只留路由与行为规则以控制每会话 token 开销；本文承接原速查内容，**按需查阅**：完整命令示例（免凭据/需凭据/门户/场馆/就业/Canvas/分享）、Python API 方法表、MCP 工具清单、各系统深挖注记。命令行为以 `westlake find` 与 `--help` 为准。

## 免凭据命令示例（可直接执行）

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
westlake program overview / curriculum / majors [--lang en]
westlake program plan 人工智能 [--detail]     # 8 专业培养方案；--detail 附课程简介
westlake program courses [--category 理工|人文|素质] [-k 关键词 --detail]
westlake program course 机器学习             # 跨源：通识 + 8 专业培养方案
westlake research --limit 10 / research detail <URL>
westlake events --days 7 --type 名家讲座 / events detail <URL>
westlake careers --category 博士后 --keyword 物理 --limit 20
westlake faculty --school 理学院 --source all|main|science|sls|teaching
westlake campus dining --campus 云谷 --kind 食堂 / campus housing --campus 云谷
westlake contact --campus 云谷               # 云谷|云栖|铜鉴湖；缺省三校区
westlake map [--campus 云谷]                 # 地址/地图图片/全景/交通
westlake sso creds show                      # 终端显示已存教务学号/密码（忘记时找回）
westlake vpn login                           # 弹窗手动输验证码，会话落盘复用
westlake vpn status / vpn resources          # 状态 / 隧道推送的内网路由
westlake sites list / sites site <key> / sites detail <url>
westlake hosts list|mine --all|show <子域> [--render]   # 全量子站探测与栏目挖掘
westlake wiki list --cat clubs / wiki search 班车 / wiki page 音游社
westlake hpc ai                              # Westlake AI 大模型网关（OpenAI 兼容）
westlake pms stations / probe / scholar open cnki
westlake cache clear --module events
westlake webui serve --port 2018             # 本地前端；/capabilities 能力总览
```

## 需 SIS 凭据 + 校园网/VPN

```bash
westlake sso creds set                       # 交互输入；--sid/--password/--keyring
westlake sso creds status / sso login
westlake sis schedule / grades / exams / cart / sis ical --out schedule.ics
westlake sis-evals list --pending
westlake profile info|academic|extended
westlake records dorm|leave|honors|volunteer|vol-history|practice|discipline|
           second-class|advisor|other-apps|appointments|registration|leaving-check|source-info
westlake aid loans|jobs|claim|outbound|exchange|orgs|activities
westlake aid orgs --wiki                     # 社团目录 + WikiLake 改写简介
westlake ams status / ams schedule --json / ams menus / ams notices
westlake lib search 数据结构 --page 1 / lib loans   # 2026-10-28 起迁移暂不可用
westlake pms jobs
```

## 门户 / 场馆 / 就业

```bash
westlake portal cards / portal chatbot
westlake sport scenes / sport sites 游泳次卡 [--date 2026-10-28]
westlake sport days 游泳次卡 游泳场次 --start … --end … / sport mine [--history]
westlake career deep --kind campus|jobfair|teachin|news --page 1
westlake career detail 1129108               # 也可用列表输出的 URL / news aid、tag
```

## Canvas（令牌或统一密码会话）

```bash
westlake canvas courses / deadlines --limit 10 / exams --days 30
westlake canvas assignments --course 概率论        # 课程给 id 或名称关键词均可
westlake canvas assignment-info --course 概率论 --assignment Assignment5 [--download ./资料]
westlake canvas files --course 概率论 --match 作业 --download ./资料
westlake canvas discussions --course 概率论 / announcements --course 概率论
westlake canvas discussion --course 马原 --topic 什么是空间
westlake canvas entries --course 马原 --topic 4123 --limit 20
westlake canvas reply --course … --topic … --text "……"          # 写操作
westlake canvas inbox --limit 20 [--unread]                      # 打开会话即标已读
westlake canvas conversation 2041 --download ./资料
westlake canvas send --conversation 2041 --text "……"             # 写操作
westlake canvas submit --course 概率论 --assignment 作业3 --file hw3.pdf [--dry-run|--yes]
westlake canvas submit --course … --assignment … --text "……"     # 文本提交
westlake canvas submission --course 概率论 --assignment 作业3
```

- 课程/作业接受 id 或名称关键词（子串唯一命中才执行；命中多个列候选；搜不到先查全名——「物理学实验 Ⅱ」搜「物理实验」搜不到）。
- `assignments` 里无截止、提交类型 `none` 的条目（ClassParticipation/Quiz）多为课堂记录，看 `assignment-info` 描述再定。
- 提交链路真机验证过（2026-10-15 真交 Lab 5：西湖 Canvas 禁学生写课程文件区，包内自动退回本人文件区上传再提交）。

## OneDrive/SharePoint 讲义分享

```bash
westlake share add 2183-lecture-notes https://westlakeu-my.sharepoint.com/:f:/g/personal/…
westlake share saved / share remove <名字>
westlake share files --name 2183-lecture-notes [--path "Advanced Labs"]
westlake share download --name 2183-lecture-notes --match day01 --out ./讲义
```

链接「组织内任何人可查看」时免账号读取；仅对特定人开放的链接报 403，只能请分享者放开。

**课程资料按需现拉，不建本地镜像**：不带 `--download` 只读元数据不写盘；不要为一次查询同步整门课。

## Python API 直用（结构化数据）

前提：与 `westlake` 同一解释器（`which/where westlake`、`pip show westlake-survival`）。

```python
from westlake_survival.context import snapshot, Level
from westlake_survival.transit import transit
print(snapshot(Level.TERSE).to_str())
for table, hhmm in transit().next_departures(limit=3):
    print(hhmm, table.campus.value)

from westlake_survival.sis import get_schedule, grades          # 需凭据+校园网
from westlake_survival import sportvenue                        # 统一密码+校园网
from westlake_survival.canvas import canvas
from westlake_survival.canvas.models import (SUBMISSION_TYPE_UPLOAD,
    SUBMISSION_TYPE_TEXT, SUBMISSION_TYPE_URL)
c = canvas()
for course in c.list_courses():                                 # 扫当前可交的作业
    for a in c.list_assignments(course.id):
        kinds = {SUBMISSION_TYPE_UPLOAD, SUBMISSION_TYPE_TEXT, SUBMISSION_TYPE_URL}
        if kinds.intersection(a.submission_types) and not a.locked_for_user:
            s = c.get_submission(course.id, a.id)
            print(course.name, a.name, a.due_at, s.workflow_state if s.submitted_at else "未交")
```

`CanvasClient` 其余方法（CLI 同名命令已覆盖大部分）：

| 方法 | 返回 / 作用 |
| --- | --- |
| `me()` / `list_courses()` / `get_course(id)` | 当前用户 / 课程列表 / 单课程 |
| `find_course(关键词)` / `find_assignment(cid, 关键词)` | 唯一定位（零命中 NotFound、多命中列候选） |
| `todo(limit)` / `modules(course_id)` | 待办（北京时间）/ 模块与条目 |
| `discussions(course_id)` / `discussion_topic(cid, tid)` / `discussion_entries(cid, tid)` | 主题列表 / 正文与附件 / 回帖 |
| `find_topic(cid, 关键词)` / `list_announcements(course_id)` | 主题唯一定位 / 公告 |
| `conversations(limit)` / `unread_count()` / `conversation(id)` | 收件箱 / 未读数 / 会话全文与附件 |
| `reply_to_discussion(cid, tid, text)` / `reply_conversation(id, body)` | 写操作：回帖 / 回私信 |
| `get_assignment(cid, aid)` / `assignment_attachments(cid, aid)` | 作业详情（含 rubric）/ 描述抽附件 |
| `list_files(course_id)` / `file_info(file_id)` / `download_file(file_id, dest)` | 文件区 |
| `submit_assignment(…)` / `get_submission(cid, aid)` | 提交（干跑/真交）/ 回读状态 |

## MCP 备选通道

零依赖 stdio 服务器，65 个工具：学业 `sis_schedule`/`sis_grades`/`sis_exams`/`sis_cart`/`sis_evals_pending`/`sis_second_class`/`sis_advisor`/`sis_other_applications` + records/aid 类；就业 `career_latest`/`career_deep`/`career_detail`；校历班车 `calendar_today`/`calendar_week`/`transit_next`；内容 `news_latest`/`events_upcoming`/`research_latest`/`site_search`/`faculty_search`/`affairs_apps`；百科 `wiki_search`/`wiki_page`；培养 `program_*` 六个；校园 `campus_dining`/`campus_housing`/`campus_map`/`contact_info`/`context_snapshot`；学术 `scholar_databases`/`scholar_resolve_doi`/`scholar_campus`；作业课程 `canvas_deadlines`/`canvas_todo`/`canvas_submit`/`canvas_files`/`canvas_assignment_info`/`canvas_discussions`/`canvas_announcements`/`canvas_inbox`/`canvas_conversation`/`canvas_discussion_entries`；分享 `share_files`；场馆 `sport_scenes`/`sport_sites`/`sport_days`/`sport_reservations`。写操作只在 CLI 提供，MCP 仅 `canvas_submit` 且需显式确认。

```json
{"mcpServers": {"westlake": {"command": "westlake-mcp"}}}
```

`westlake-mcp` 不在 PATH 时：`"command": "python", "args": ["-m", "westlake_survival.mcp_server"]`。

## 深挖注记（按需）

- **图书馆（2026-10-28 迁移）**：老阿法迪 OPAC `/opac/*` 整体下线，学校换「阿法迪云 eLibrary」（内网 `172.16.10.223:8180/page/login.jsp`，平台自有账号；公网别名只剩首页快照）。`lib` 命令会说明现状并退出、不再试已失效的 CAS 登录（反复失败有锁号风险）；WebUI 图书馆页已下线。接新平台需本人浏览器登录一次后重探接口——docs/library_migration_2026-10-28.md。
- **预约四套系统**（2026-10-27 审计）：预约中心 17 类场地；体育场馆/游泳在 sportvenue（登录已通、卡服务端「表单规则未找到」，docs/sportvenue_notes.md）；图书馆座位在 seats.library（企业微信微应用，浏览器拿不到 accessToken）；办事大厅另有 CGYY/ResourceReservation 两个流程表单（发起即建流程实例，属写操作）。对照表 docs/module_audit_2026-10-27.md。
- **学术资源**：本校是 CARSI 联盟成员，统一密码可登录各出版社；校园网内按 IP 认账。`scholar doi` 走「OA 副本（OpenAlex）→ 出版社 citation_pdf_url」两级取全文。
- **门户服务目录 `affairs portal`**：2026-10-27 实测服务端接口疑似变化暂报错，网页区块自动降级。
- **Canvas 事实口径**：待办/讨论时间是 UTC；作业对象无 attachments 字段，题目附件在描述 HTML 的文件链接；题目文件可能挂三处（描述/文件区/模块）。
