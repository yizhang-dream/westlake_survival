---
name: westlake-survival
description: 西湖大学校园一站式工具（学业/教学/科研/生活/办事/信息六域）。学业：课表（SIS 与教学系统 AMS 两套）、成绩、考试安排、评教、第二课堂、个人信息/学籍/住宿/荣誉/志愿/资助/社团；Canvas：课程、作业截止、考试测验、作业详情与题目附件（含评分细则）、课程文件下载、讨论区与公告、收件箱，以及交作业/回帖/回私信三类写操作；学术科研：订阅数据库清单、CARSI 校外登录（westlake scholar ensure 一条命令）、DOI→PDF 论文全文下载、科研进展、导师名录、HPC 集群队列、报销与科研经费制度；就业：招聘岗位、招聘会、宣讲会；生活：校历周次与假期、班车时刻、食堂咖啡、公寓、校区地图与全景、自助打印、图书馆借阅、预约中心场地预约（研讨室/研习仓逐日空闲与预约、取消；体育场馆/游泳与图书馆座位在独立系统，入口与卡点见文档）；办事：办事大厅目录、我的待办、门户个人卡片；信息：新闻、讲座活动、学院动态、全站搜索、93 服务注册表与在线普查。凡与西湖大学（Westlake）相关的查询或操作需求都可使用——包括但不限于「查/交作业、下周什么考试、几号放假、下一班校车、找论文并下载全文、校外访问数据库、我借了什么书、打印点在哪、报销规定、今天有什么讲座/待办、找某位老师、宿舍与荣誉记录、跑普查找服务」。不确定某需求归哪条命令时，先运行 westlake find <需求关键词>（口语同义词可命中，如「论文」「借书」「放假」）。
---

# 西湖大学生存手册（westlake-survival）

把西湖大学各服务系统收敛为一条 CLI / 一套 Python API / 一个 MCP 服务器。**默认只读**：写操作仅限五条，且都必须凭用户当轮明确指令执行——`canvas submit` 交作业、`canvas reply` 讨论回帖、`canvas send` 回私信、`booking book` 预约场地、`booking cancel` 取消预约；不做选课、抢课等其他写操作。

本文只放路由与行为规则；**完整命令示例、Python API 方法表、MCP 工具清单在 [docs/skill_reference.md](../../../docs/skill_reference.md)**，各系统深挖见 docs/ 对应文档（按需再读，不必全量加载）。

## 环境自检（Agent 接手第一步）

先跑 `westlake doctor`（不在 PATH 就 `python -m westlake_survival doctor`；`--json` 便于判断）。逐项体检解释器/包/命令一致性/依赖/账号/网络，缺什么给一条能直接抄的修复命令；退出码 0=可用、1=有缺失，全绿再干活。

- **缺什么就装什么**（只装 Python 依赖，可直接执行）：`pip install -e .` 一条就齐——Flask/keyring 都是基础依赖，装完即有网页与加密凭据存储。`.[browser]`（playwright + `playwright install chromium`）是**可选增强**：缺它 doctor 只报 warn 不挡活，share 讲义/hosts 渲染深挖/CARSI 校外 SSO 三条链路自动降级，**没有浏览器也能用**。Linux 无桌面：钥匙串取不到后端时退明文文件（warn）、playwright 缺系统库补 `playwright install-deps chromium`。
- **解释器必须一致**：`westlake`、`python -m westlake_survival`、自写脚本要用同一个解释器，否则「明明装了却 import 不到」。查法：`which westlake`（macOS/Linux）/ `where westlake`（Windows）、`pip show westlake-survival`；不一致就改用 `python -m westlake_survival` 对齐。
- **账号不由 Agent 填**：doctor 报「校园账号 未配置」时，请用户本人跑 `westlake`（或启动脚本 `start.bat` / `start.command` / `start.sh`）在网页「设置」页填一次；不要索取、不要代填、不要写凭据文件。做隔离测试用临时 `WESTLAKE_HOME` 或 `WESTLAKE_NO_KEYRING=1`——**两者任一成立即沙箱**，钥匙串读写都跳过。
- **网络**：库层默认直连（无视 `HTTP_PROXY/HTTPS_PROXY`）；校外访问教务/Canvas 需 VPN，先 `westlake vpn status`。

## 能力路由

不确定归哪条命令先 `westlake find <需求关键词>`（口语可命中）。下表命令均省略 `westlake ` 前缀：

| 用户想问 | 命令 |
| --- | --- |
| 环境不对 / 装了用不了 / 不知道归哪条 | `doctor` / `find <关键词>` |
| 今天几号 / 第几周 / 校历事件 / 学期 | `calendar today` / `week N` / `events` |
| 下一班校车 / 班车时刻 / 课表班车 ICS | `transit next` / `table` / `transit ical`（网页 /ical 一键复制） |
| 一句话「此刻西湖」/ 每日晨报 | `context` / `digest` |
| SIS 课表 / 成绩 / 考试 / 选课车 / ICS | `sis schedule` / `grades` / `exams` / `cart` / `sis ical` |
| 教学系统 AMS 课表 / 周次 / 学籍选课入口 | `ams schedule`（`--start/--end`）/ `status` / `menus`（与 SIS 两套，走 IAM） |
| 待评教 / 第二课堂 / 导师 / 学籍异动 | `sis-evals list --pending` / `records second-class` / `records advisor` / `records other-apps` |
| 个人信息 / 住宿 / 荣誉 / 志愿 / 资助 / 社团 | `profile info\|academic\|extended` / `records` 系列 14 子命令 / `aid` 系列 7 子命令（find 可查全名） |
| Canvas 课程 / 截止 / 测验 / 待办 / 模块 | `canvas courses` / `deadlines` / `exams` / `todo` / `modules` |
| 某作业题目描述 / 附件（可下载）/ 评分细则 | `canvas assignment-info --course … --assignment … [--download 目录]` |
| 课程文件区 / 讨论区 / 公告 / 收件箱 | `canvas files` / `discussions` / `announcements` / `inbox`；主题与回帖 `canvas discussion` / `entries` |
| 交作业 / 回帖 / 回私信（写操作）/ 提交状态 | `canvas submit`（`--dry-run` 预检）/ `reply` / `send` / `submission` |
| 老师的 OneDrive/SharePoint 讲义 | `share add 名字 链接` 登记一次，`share files` / `download --match` |
| 学术数据库清单 / 某库入口 / DOI→PDF | `scholar dbs` / `open cnki` / `doi <doi> -o out.pdf`（校园网订阅通道） |
| 校外用数据库 / 共享会话 | `scholar ensure`（会话活零动作→无头登录→必要时弹浏览器本人输一次验证码） |
| 本科培养方案 / 课程体系 / 专业 / 通识课 | `program plan [专业]` / `curriculum` / `majors` / `courses` / `course <关键词>` |
| 新闻 / 讲座活动 / 科研进展 / 导师名录 / 招聘 | `news` / `events` / `research` / `faculty` / `careers`；就业深列表 `career deep --kind campus\|jobfair\|teachin`、详情 `career detail <id>` |
| 官网全站搜索 / 站点栏目 / 全量子站 | `search <关键词>` / `sites list\|site\|detail` / `hosts list\|mine\|show` |
| 学生百科 WikiLake | `wiki list` / `search <关键词>` / `page <条目>` |
| 食堂 / 公寓 / 电话 / 地图全景 | `campus dining` / `housing` / `contact phones` / `map [--campus 云谷]` |
| 什么事在哪儿办 / 我的待办 / 部门站点 | `affairs apps [关键词]` / `links` / `todo list\|doing\|done\|cc\|apps` |
| 门户个人卡片（未读邮件/在借/待办）/ AI 助手 | `portal cards` / `portal chatbot` |
| 打印网点 / 我的打印任务 | `pms stations` / `jobs` |
| 图书馆书目 / 我的借阅 | **暂不可用**（2026-10-28 系统迁移；命令会说明现状，见 docs/library_migration_2026-10-28.md） |
| 场地预约：分类 / 房间 / 哪天能约 / 空闲时段 | `booking types` / `list --type 图书馆` / `days <房间> --start … --end …` / `slots <房间> --date …` |
| 预约 / 取消预约（写操作）/ 我的预约 | `booking book`（`--dry-run` 可预检）/ `cancel <预约号> --reason …` / `mine` |
| 体育场馆 / 游泳场次（独立正元系统，只读） | `sport scenes` / `sites <场景> [--date]` / `days <场景> <场地>` / `mine` |
| 预约类需求为什么约不了 / 从哪进 | `probe` + `affairs apps 预约`；四套系统对照 docs/module_audit_2026-10-27.md |
| HPC 集群 / 报销制度 / 镜像站 | `hpc overview` / `finance sections\|articles` / `mirrors` |
| 服务是否可达 / 服务全景普查 | `probe` / `probe scan [--full]`（网页 /services、/capabilities） |
| VPN 登录 / 状态 / 隧道资源 | `vpn login` / `status` / `resources` |
| 一步打开全部功能 | 裸跑 `westlake`（起 WebUI 自动开浏览器，未配账号直达 /setup） |

## 用户入口（网页第一）

用户侧双击 `start.bat`（Windows）/ `start.command`（macOS）/ 终端 `./start.sh`（Linux），或裸跑 `westlake`：浏览器自动打开，没配过账号**直达 `/setup`** 填一次学号+统一密码（Canvas 令牌选填，可一键清除；验证不过也落盘，不必重填）。**保存并验证通过后 3 秒自动进仪表盘**（未验证则留在设置页）；终端路径要 `westlake setup --open` 才主动拉起前端（默认不弹——CLI setup 常由 Agent 代跑；`WESTLAKE_NO_WEBUI=1` 硬关）。Agent 侧等价 `westlake setup`（含 `--canvas-token '<令牌>' --no-verify` 保存、`--clear-canvas-token` 删除）。统一密码通吃 SIS/Canvas/AMS/打印/预约/门户/体育。

## 凭据前提（先判断再执行，缺凭据就换命令）

- **SIS 类**（`sis`/`sis-evals`/`profile`/`records`/`aid`/`pms jobs`）：先 `westlake sso creds set` 写学号密码，且只在校园网/VPN 内可达。
- **AMS**：同一套统一密码走 IAM 统一认证（经典 CAS 不接该 service）；会话缓存 8h；只读，选课学籍修改进系统做。见 docs/ams.md。
- **Canvas**：优先令牌（/setup、`WESTLAKE_CANVAS_TOKEN`、`~/.westlake_survival/canvas_token.txt`）；**无令牌自动回退统一密码会话**。报 401 先怀疑存了过期令牌：`westlake setup --clear-canvas-token` 回退统一密码。
- **预约中心**：统一密码 OIDC 自动登录；接口对没权限的分类只返回空列表，能不能约看 `booking types`。
- **sport**：统一密码 IAM CAS 自动登录；只读不做预约（下单涉次卡支付未接）。
- **无凭据照常可用**：`calendar`/`transit`/`context`/`digest`/`search`/`news`/`program`/`research`/`events`/`careers`/`faculty`/`campus`/`map`/`contact`/`pms stations`/`probe`/`cache` 与 `scholar dbs|campus|doi|carsi|open`。
- **凭据只存一份**：钥匙串或明文文件二选一，写入自动清另一份；`sso creds status` 只报来源有无。**登录报密码错别反复试**——IAM 失败计数触发图形验证码（14h+ 不复位）。凭据是本机状态，换机器/用户/环境各配一次。

## 卡点归因（先归因，再谈能不能做）

用户说「做不了」时别直接记成「系统不支持」，先五问：①**锚定**——绑死单一系统了？（「预约」≠只有预约中心，还有 sportvenue/seats/CGYY 表单）②**时效**——依据是旧通知？③**占位符**——「外链/暂未接入」是线索不是结论④**搜不到**≠不存在⑤卡一轮就问用户平时从哪进。

判定前三跑（只读、几十秒）：`probe`、`hosts list`、`affairs apps 预约`。结论必归四类之一：**真做不了**（权限/网络/服务端缺失）/ **没建工具** / **逆向没做完** / **我判断错了**。对照清单 docs/module_audit_2026-10-27.md；新系统登记进 `discovery.EVIDENCE_HOSTS`。

改任何解析层前后各跑 `python tools/module_smoke.py`（51 条只读命令体检）；**新增模块必须在其中登记一条只读命令**。并发硬规则：同账号最多 2 路登录；见 `4333 验证码或登录名为空` 立即停手不重试。

## Agent 行为守则

- **网络一律直连（库层已内置）**：所有会话默认 `trust_env=False`；Agent 自己写脚本抓校园站点也必须显式直连（`requests` 传 `trust_env=False`，或复用 `westlake_survival.discovery.direct_session()`）；唯一例外 HPC 成果库代理兜底。诊断「连不上」先排除代理劫持。
- **默认只读，写操作仅五条且要当轮明确指令**：`canvas submit`/`reply`/`send`、`booking book`/`cancel`。只凭用户当轮给出的对象与内容执行，不构造未文档化的请求。
- **交作业三步走**：①`--dry-run` 预检；②提交（用户点名文件即视为授权）；③`canvas submission` 回读核验（submitted、附件名、未迟交）后才报完成。已评分作业默认不重交。
- **回帖与私信先确认**：`canvas reply`/`send` 默认打印将发送内容等确认，`--yes` 才发；发完回读核对落地；`cannot_reply` 的会话直接拒绝。
- **写作业内容先看课程资料**：动笔前看 `assignment-info`（描述与附件）、`files`、`modules`——题目文件可能在三处任一处，描述里没有不代表没有。不要假定资料在固定本地路径。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的有无。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等输出给第三方前默认脱敏/摘要提示。
- **失败降级**：`OffCampusError`=需校园网/VPN（<https://vpn.westlake.edu.cn/>）；`AuthError`=凭据缺失/失效（`westlake sso creds set`）；命令失败如实转述错误，不臆造数据。
