# 命令与接口参考（skill_reference）

> 本文汇总 westlake_survival 的常用命令示例、Python API 方法表、MCP 工具清单与系统适配注记，供按需查阅。具体命令用法以 `westlake find` 与 `--help` 输出为准。

## 免凭据命令示例（可直接执行）

```bash
westlake calendar today                      # 今日日期/学期/周次/事件（支持 --offline）
westlake calendar week 4                     # 第 4 周起止日期
westlake calendar events                     # 本学期校历事件
westlake transit next --campus 云谷 --limit 3 # 下一班班车时刻与接驳建议
westlake transit table --campus 云谷 --day 工作日 # 班车时刻表（支持 --offline）
westlake transit ical --days 14 --out bus.ics # 导出班车日历文件
westlake booking recommend --date today --min-hours 1.5 # 复合求解：智能推荐空闲连续场地
# 网页订阅：校历页有班车/课表 ICS 一键复制（/ical/shuttle、/ical/schedule）
westlake context --level terse               # terse|normal|verbose
westlake digest --level normal               # 每日摘要；terse 仅计算本地指标
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
westlake campus services --campus 云谷       # 超市/快递/干洗/理发/打印/银行
westlake contact --campus 云谷               # 云谷|云栖|铜鉴湖；缺省三校区
westlake map [--campus 云谷]                 # 地址/地图图片/全景/交通
westlake sso creds show                      # 终端显示已存教务学号/密码（忘记时找回）
westlake vpn login                           # 弹窗手动输验证码，会话落盘复用
westlake vpn status / vpn resources          # 状态 / 隧道推送的内网路由
westlake sites list / sites site <key> / sites detail <url>
westlake hosts list|mine --all|show <子域> [--render]   # 全量子站探测与栏目挖掘
westlake wiki list --cat clubs / wiki search 班车 / wiki page 音游社
westlake lib search "数据结构"                # 新版阿法迪云平台公开检索书目（题名/作者/索书号/馆藏地）
westlake lib loans                           # 个人在借图书与应还时间（新平台长效 JWT 会话）
westlake hpc ai                              # Westlake AI 大模型网关（OpenAI 兼容）
westlake hpc chat "提示词"                    # 终端直接调用学校 GPU 集群大模型对话（deepseek/glm/qwen，免费）
westlake hpc sync-key                        # 基于统一认证自动领取并配置集群私有令牌
westlake portal ask "问题"                    # 向校内官方 AI 问答助手提问（办事/规章/生活答疑）
westlake instrument search "质谱"             # 检索全校大型科学仪器设备（地点/联系人/电话/预约入口）
westlake instrument list --limit 20          # 浏览大仪共享平台最新设备清单
westlake affairs app <名称>                   # 查看办事大厅流程应用的详细说明与表单直达链接
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
westlake pms stations                           # 打印网点列表（无需登录）
westlake pms jobs                               # 我的未打印作业（需登录）
westlake pms print doc.pdf [--copies 2] [--duplex] [--color] [--from-page N --to-page N]  # 上传并创建云打印作业（写操作，带 Action Card）
westlake pms cancel 12345                       # 取消并删除未打印作业（写操作，带 Action Card；刷卡前撤回无损）
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
westlake canvas courses [--past|--all] / canvas grades [--past|--all] / deadlines --limit 10 / exams --days 30
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
westlake canvas star 2183 / canvas unstar 2183                   # 课程收藏/星标置顶（写操作）
westlake canvas upload ./notes.pdf                               # 上传本地文件至个人 Canvas 云盘（写操作）
westlake canvas dismiss-todo 8857                                # 忽略/归档 Canvas 个人待办事项（写操作）
westlake canvas submit --course 概率论 --assignment 作业3 --file hw3.pdf [--dry-run|--yes]
westlake canvas submit --course … --assignment … --text "……"     # 文本提交
westlake canvas submission --course 概率论 --assignment 作业3
westlake lib renew 12345678                                      # 在借图书在线续借（写操作，带 Action Card 校验）
```

- 课程/作业接受 id 或名称关键词（子串唯一命中才执行；命中多个列候选；搜不到先查全名——「物理学实验 Ⅱ」搜「物理实验」搜不到）。
- `assignments` 里无截止、提交类型 `none` 的条目（ClassParticipation/Quiz）多为课堂记录，看 `assignment-info` 描述再定。
- 提交链路经端到端验证（西湖 Canvas 禁止学生直接向课程公共文件区写入，包内自动切换至个人文件区上传后再提交）。

## OneDrive/SharePoint 讲义分享

```bash
westlake share add 2183-lecture-notes https://westlakeu-my.sharepoint.com/:f:/g/personal/…
westlake share saved / share remove <名字>
westlake share files --name 2183-lecture-notes [--path "Advanced Labs"]
westlake share download --name 2183-lecture-notes --match day01 --out ./讲义
westlake share login                             # 登录西湖微软账号（弹窗交互），捕获并保存组织会话
westlake share login --cookie "FedAuth=...; …"   # 纯文本注入 Cookie（免弹窗）
westlake share auth-status / share logout        # 查看组织登录态 / 清除会话
```

公开链接免账号匿名读取；需要登录的组织内限制分享通过 `westlake share login` 完成一次登录后长期自动复用。

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
| `me()` / `list_courses([state])` / `list_past_courses()` / `get_course(id)` | 当前用户 / 课程列表（在修/过往结课/全部）/ 过往结课课程 / 单课程 |
| `find_course(关键词)` / `find_assignment(cid, 关键词)` | 唯一定位（零命中 NotFound、多命中列候选；自动回退过往课程） |
| `todo(limit)` / `modules(course_id)` | 待办（北京时间）/ 模块与条目 |
| `discussions(course_id)` / `discussion_topic(cid, tid)` / `discussion_entries(cid, tid)` | 主题列表 / 正文与附件 / 回帖 |
| `find_topic(cid, 关键词)` / `list_announcements(course_id)` | 主题唯一定位 / 公告 |
| `conversations(limit)` / `unread_count()` / `conversation(id)` | 收件箱 / 未读数 / 会话全文与附件 |
| `reply_to_discussion(cid, tid, text)` / `reply_conversation(id, body)` | 写操作：回帖 / 回私信 |
| `get_assignment(cid, aid)` / `assignment_attachments(cid, aid)` | 作业详情（含 rubric）/ 描述抽附件 |
| `list_files(course_id)` / `file_info(file_id)` / `download_file(file_id, dest)` | 文件区 |
| `submit_assignment(…)` / `get_submission(cid, aid)` | 提交（预检/实际提交）/ 回读状态 |

## MCP 备选通道

零依赖 stdio 服务器，82 个工具：学业 `sis_schedule`/`sis_grades`/`sis_exams`/`sis_cart`/`sis_evals_pending`/`sis_second_class`/`sis_advisor`/`sis_other_applications` + records/aid 类；就业 `career_latest`/`career_deep`/`career_detail`；校历班车 `calendar_today`/`calendar_week`/`transit_next`；内容 `news_latest`/`events_upcoming`/`research_latest`/`site_search`/`faculty_search`/`affairs_apps`；百科 `wiki_search`/`wiki_page`；培养 `program_*` 六个；校园 `campus_dining`/`campus_housing`/`campus_map`/`contact_info`/`context_snapshot`；学术 `scholar_databases`/`scholar_resolve_doi`/`scholar_campus`；作业课程 `canvas_courses`/`canvas_deadlines`/`canvas_todo`/`canvas_submit`/`canvas_files`/`canvas_assignment_info`/`canvas_discussions`/`canvas_announcements`/`canvas_inbox`/`canvas_conversation`/`canvas_discussion_entries`；分享 `share_files`；文印 `pms_stations`/`pms_jobs`；场馆 `sport_scenes`/`sport_sites`/`sport_days`/`sport_reservations`。写操作工具缺省只预检、`confirm=true` 才执行：`canvas_submit`、`pms_print`、`pms_cancel`（其余写操作仅在 CLI 提供，走 Action Card 确认门）。

```json
{"mcpServers": {"westlake": {"command": "westlake-mcp"}}}
```

`westlake-mcp` 不在 PATH 时：`"command": "python", "args": ["-m", "westlake_survival.mcp_server"]`。

## 深挖注记（按需）

- **图书馆接入架构**：老阿法迪 OPAC 下线后，已全面适配「阿法迪云 eLibrary」（`mylib.westlake.edu.cn`），打通公开书目检索（`lib search`）、在借图书（`lib loans`）与在线续借（`lib renew`，受控写操作），详见 docs/library.md。
- **自助文印（联创 UniFound）**：入口 `print.lib.westlake.edu.cn:9130`，校园卡号 + 统一密码。打印机分布——云栖图书馆（五号楼一楼）与云谷图书馆师生服务中心（A2-413），各一台黑白 + 一台彩色（彩打勿选错机器，实时状态看 `pms stations`）。云打印支持 `.jpg/.png/word/excel/.pdf/.txt/.ppt`，可设份数、单双面（长/短边）、黑白/彩色、页码范围；上传进队列后**任意自助机**刷卡两次取件（首刷验证、二刷扣款），**刷卡前不扣费**、`pms cancel` 可无损撤回。扫描件扫完在云平台「扫描文档」下载。故障联系信息技术中心 87025797 / it@westlake.edu.cn（图书馆 library@westlake.edu.cn）。（要点依据 2026-11 图书馆《自助文印服务使用手册》）
- **预约四套系统**：预约中心 17 类场地；体育场馆/游泳在 sportvenue（登录已通、卡服务端「表单规则未找到」，docs/sports.md）；图书馆座位在 seats.library（企业微信微应用，浏览器拿不到 accessToken）；办事大厅另有 CGYY/ResourceReservation 两个流程表单。对照表 docs/module_audit.md。
- **学术资源**：本校是 CARSI 联盟成员，统一密码可登录各出版社；校园网内按 IP 认账。`scholar doi` 走「OA 副本（OpenAlex）→ 出版社 citation_pdf_url」两级取全文。
- **门户服务目录 `affairs portal`**：2026-10-27 实测服务端接口疑似变化暂报错，网页区块自动降级。
- **门户数据市集**：技能内 `scripts/data_market.py` 支持目录与本人档案、履历、已修课程、荣誉、社团、志愿七类只读查询，自动完成会话交换与分页；尚无专用 CLI/MCP。调用方法、进程内取值、认证步骤和目录权限边界统一维护在[数据市集只读指南](../skills/westlake-survival/references/data-market.md)。
- **Canvas 事实口径**：待办/讨论时间是 UTC；作业对象无 attachments 字段，题目附件在描述 HTML 的文件链接；题目文件可能挂三处（描述/文件区/模块）。
