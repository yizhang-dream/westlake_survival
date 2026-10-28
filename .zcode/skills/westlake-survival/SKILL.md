---
name: westlake-survival
description: 西湖大学校园一站式工具（学业/教学/科研/生活/办事/信息六域）。学业：课表（SIS 与教学系统 AMS 两套）、成绩、考试安排、评教、第二课堂、个人信息/学籍/住宿/荣誉/志愿/资助/社团；Canvas：课程、作业截止、考试测验、作业详情与题目附件（含评分细则）、课程文件下载、讨论区与公告、收件箱，以及交作业/回帖/回私信三类写操作；学术科研：订阅数据库清单、CARSI 校外登录（westlake scholar ensure 一条命令）、DOI→PDF 论文全文下载、科研进展、导师名录、HPC 集群队列、报销与科研经费制度；就业：招聘岗位、招聘会、宣讲会；生活：校历周次与假期、班车时刻、食堂咖啡、公寓、校区地图与全景、自助打印、图书馆借阅、预约中心场地预约（研讨室/研习仓逐日空闲与预约、取消；体育场馆/游泳与图书馆座位在独立系统，入口与卡点见文档）；办事：办事大厅目录、我的待办、门户个人卡片；信息：新闻、讲座活动、学院动态、全站搜索、93 服务注册表与在线普查。凡与西湖大学（Westlake）相关的查询或操作需求都可使用——包括但不限于「查/交作业、下周什么考试、几号放假、下一班校车、找论文并下载全文、校外访问数据库、我借了什么书、打印点在哪、报销规定、今天有什么讲座/待办、找某位老师、宿舍与荣誉记录、跑普查找服务」。不确定某需求归哪条命令时，先运行 westlake find <需求关键词>（口语同义词可命中，如「论文」「借书」「放假」）。
---

# 西湖大学生存手册（westlake-survival）

把西湖大学各服务系统收敛为一条 CLI / 一套 Python API / 一个 MCP 服务器。**默认只读**：本技能以查询与导出为主；写操作仅限五条，且都必须凭用户当轮明确指令执行——`canvas submit` 交作业、`canvas reply` 讨论回帖、`canvas send` 回私信、`booking book` 预约场地、`booking cancel` 取消预约（见下）；不做选课、抢课等其他写操作。

## 环境自检（Agent 接手第一步）

先跑 `westlake doctor`（命令不在 PATH 就用 `python -m westlake_survival doctor`，`--json` 便于判断）。它检查解释器版本、包本体、命令与解释器是否同一个环境、依赖（flask 基础依赖 / keyring / playwright）、账号有无、直连网络，每一项缺失都给一条可直接抄的修复命令；全绿再干活，退出码 0=可用、1=有缺失。

- **缺什么就装什么**，命令都写在输出的「修复」列里，通常是 `pip install -e .`（Flask 自 2026-10-28 起是基础依赖，装完就有网页前端）/ `pip install -e '.[secure]'` / `playwright install chromium`。这些只装 Python 依赖，不碰系统凭据，可以直接执行。
- **解释器必须一致**：`westlake` 命令、`python -m westlake_survival`、以及你自己写的 Python 脚本要用同一个解释器，否则「明明装了却 import 不到」。doctor 报「不是同一个环境」时，改用 `python -m westlake_survival` 调用即可对齐。
- **账号不由 Agent 填**：doctor 报「校园账号 未配置」时，请用户本人跑 `westlake`（或双击 `start.bat`）在网页「设置」页填一次；不要索取、不要代填、不要写凭据文件。做隔离测试用临时 `WESTLAKE_HOME` 或 `WESTLAKE_NO_KEYRING=1`——**两者任一成立即沙箱**，钥匙串读写都跳过，绝不改本机真实凭据。
- **网络**：库层默认直连（无视 `HTTP_PROXY/HTTPS_PROXY`）；校外访问教务/Canvas 需 VPN，先 `westlake vpn status` 看状态。

## 能力地图：哪类问题用哪条命令

| 用户想问 | 命令 |
| --- | --- |
| **环境不对 / 装了却用不了 / 缺依赖** | **`westlake doctor`**（解释器、依赖、账号、网络逐项体检 + 修复命令） |
| **不知道这需求归哪条命令 / 这 skill 能干什么** | **`westlake find <需求关键词>`**（搜 CLI/MCP/网页/学术库/服务注册表，口语可命中） |
| 今天几号 / 第几周 / 什么学期 / 今日校历 | `westlake calendar today` |
| **教学系统的课表 / 教学周次**（AMS，与 SIS 课表是两套） | `westlake ams schedule`（默认本周，`--start/--end` 指定区间） / `westlake ams status` |
| 学籍信息 / 学生选择导师 / **选课** / 我的课表 入口 | `westlake ams menus`（只读，给的是系统内链接；写操作进系统做） |
| 本学期第 N 周的起止日期 | `westlake calendar week <N>` |
| 校历事件（开学、假期、考试周） | `westlake calendar events` |
| 下一班校车 / 某校区班车时刻表 | `westlake transit next` / `westlake transit table` |
| 一句话「此刻西湖」（日期+周次+事件+班车+天气） | `westlake context` |
| 每日晨报（快照+活动+班车+周次+Canvas） | `westlake digest` |
| 我的课表 / 成绩 / 考试安排 / 选课车 | `westlake sis schedule` / `grades` / `exams` / `westlake sis cart` |
| 待评教任务 | `westlake sis-evals list --pending` |
| 第二课堂成绩单（5 维度 + 每项进度） | `westlake records second-class` |
| 学业导师（分配结果 + 两轮名单） | `westlake records advisor` |
| 学籍异动流程 / 困难认定 / 本博衔接 / 就业状态 | `westlake records other-apps` |
| 我的个人信息 / 学籍 / 紧急联系人 | `westlake profile info` / `academic` / `extended` |
| 住宿 / 请假 / 荣誉 / 志愿 / 实践 / 违纪 | `westlake records dorm` 等（见下） |
| 贷款 / 勤工助学 / 海外交流 / 社团 | `westlake aid loans` 等（见下） |
| Canvas 课程 / 作业截止 / 测验考试 | `westlake canvas courses` / `deadlines` / `exams` |
| 列出某课程的作业（查作业 id/名称） | `westlake canvas assignments --course <id或关键词>` |
| 看作业题目描述与附件（可下载） | `westlake canvas assignment-info --course … --assignment … [--download 目录]` |
| 作业评分细则 / 允许的扩展名 / 提交次数 | `westlake canvas assignment-info …`（同一条命令输出） |
| 课程文件区清单 / 批量下载 | `westlake canvas files --course … [--match 关键词] [--download 目录]` |
| 课程讨论区 / 课程公告 | `westlake canvas discussions --course …` / `westlake canvas announcements --course …` |
| 讨论主题正文 / 回帖列表 | `westlake canvas discussion --course … --topic …` / `westlake canvas entries …` |
| 收发站内信（收件箱） | `westlake canvas inbox` / `westlake canvas conversation <会话id>`；回信 `canvas send`（写操作） |
| 发讨论回帖（写操作） | `westlake canvas reply --course … --topic … --text "…"` |
| 交作业（文件/文本/链接，写操作） | `westlake canvas submit --course … --assignment … --file 路径` |
| 查看某作业已提交状态 | `westlake canvas submission --course … --assignment …` |
| 老师用 OneDrive/SharePoint 共享的讲义（列文件 / 下载） | `westlake share files --name <名字>` / `westlake share download --name <名字> [--path 子目录] [--match 关键词]`；首次用 `westlake share add <名字> <链接>` 登记 |
| 讲座 / 学术会议 / 演出预告 | `westlake events` |
| 西湖新闻 / 科研进展 | `westlake news` / `westlake research` |
| 本科培养方案 / 课程体系 / 专业介绍 | `westlake program plan [专业]` / `curriculum` / `majors` / `overview` |
| 某门课几学分、哪个专业有、先修是什么 | `westlake program course <关键词>` |
| 通识课程清单（学分/开课学期/教师） | `westlake program courses [--category 理工\|人文\|素质]` |
| 官网全站搜索 | `westlake search <关键词>` |
| 招聘岗位 / 导师名录 | `westlake careers` / `westlake faculty` |
| 校园招聘/招聘会/宣讲会/新闻资讯（就业服务网） | 免登录首页三区块 `westlake career list [--kind campus\|jobfair\|teachin]`；登录态全量 `westlake career deep --kind campus --page 1`、详情 `westlake career detail <id>`，网页 `/careers` 下半区 |
| 食堂咖啡 / 公寓 / 电话地址 | `westlake campus dining` / `housing` / `contact phones` |
| 校区地图 / 校园全景 / 怎么到校 | `westlake map [--campus 云谷]` |
| 什么事在哪儿办（全校流程应用目录） | `westlake affairs apps [关键词]` |
| HPC / 预约中心 / 镜像站入口 | `westlake affairs links` |
| 集群队列与节点配置（公开） | `westlake hpc overview`，网页 `/hpc` |
| 报销/财务制度/科研经费文档 | `westlake finance sections/articles`，网页 `/finance` |
| 镜像仓库目录与换源 | `westlake mirrors`；网页 `/mirrors` 当前 500（模板取数函数缺失待修，2026-10-27 实测） |
| 全站服务注册表与在线普查 | 网页 `/services`（93 项全接入：方式徽标+扫描按钮） |
| 全量子站（探测 + 栏目挖掘） | `westlake hosts list|mine --all|show <子域>`（mine/show 可加 `--render` 用无头浏览器渲染 JS 站），网页 `/hosts` |
| 待办 / 进行中 / 已处理 / 抄送 / 我的应用（办事大厅） | `westlake todo list|doing|done|cc|apps`，网页 `/affairs`（统一密码，请求直登） |
| 门户服务目录（18 部门站点；2026-10-27 实测服务端接口疑似变化，命令暂报错） | `westlake affairs portal`（当前抛 WestlakeError 待修），网页 `/affairs`「门户服务」（该区块自动降级） |
| 门户个人卡片（未读邮件/在借图书/待办） / AI 助手入口 | `westlake portal cards` / `westlake portal chatbot` |
| 理论科学研究院新闻/学术活动 | `westlake institute news|events`，网页 `/institute` |
| 五学院官网最新新闻（理/生/工/医/理论院）；学院清单 | `westlake schools news <学院>` / `schools list`，网页 `/schools` |
| 服务全景普查（直连子域+办事目录） | `westlake probe scan [--full]`，网页版在 `/capabilities`「运行普查」 |
| 课表/成绩/考试/待评教/第二课堂/导师（网页） | WebUI `/sis`（24 块） |
| Canvas 课程/截止/待办/模块文件（网页） | WebUI `/canvas`；待办 `westlake canvas todo`，模块 `canvas modules <课程>` |
| 招聘岗位（网页） | WebUI `/careers` |
| 打印网点 / 我的打印任务 | `westlake pms stations` / `jobs`，网页 `/pms` |
| 场馆场景/当日可约/我的预约（网页） | 网页 `/sport`（体育场馆与游泳；独立系统） |
| 图书馆书目 / 我的借阅 | **暂不可用**（2026-10-28 系统迁移，见下方「图书馆」条）；`westlake lib search <关键词>` / `loans` 会直接说明现状；WebUI 该页已下线（2026-10-28 用户裁定） |
| 我能预约哪些场地（分类） | `westlake booking types` |
| 自习/研讨室有哪些、在哪层 | `westlake booking list --type 图书馆 [--keyword 研习仓]` |
| 某房间哪天能约 | `westlake booking days "E12-302研讨室" --start 2026-10-27 --end 2026-11-02` |
| 某房间某天的空闲时段 | `westlake booking slots "E12-302研讨室" --date 2026-10-27 [--duration 120]` |
| 预约场地（写操作） | `westlake booking book "4楼研习仓A" --date … --start 19:00 --end 21:00 [--dry-run]` |
| 我的预约 / 取消 | `westlake booking mine`；`westlake booking cancel <预约号> --reason …` |
| 有哪些球场/游泳场次、哪天能约 | `westlake sport scenes` / `sport sites <场景> [--date]` / `sport days <场景> <场地> --start … --end` |
| 我的场馆预约（进行中/历史） | `westlake sport mine [--history]` |
| 游泳/体育场馆为什么约不了 | `westlake sport days 游泳次卡 游泳场次`（不可约时给服务端原话）+ `westlake booking sports`（确认预约中心确实没有体育类）；卡点见 docs/sportvenue_notes.md |
| 场馆/座位/游泳从哪个入口进 | `westlake probe`（新增「场馆/座位入口」项）+ `westlake affairs apps 预约`；四套系统对照见 docs/module_audit_2026-10-27.md |
| 学术数据库清单与访问通道 | `westlake scholar dbs [-k 关键词]`，网页 `/scholar` |
| 某篇论文（DOI）的题录/PDF | `westlake scholar doi <doi> [-o out.pdf]`（校园网内走订阅通道直下） |
| 某数据库的直达/CARSI 入口 URL | `westlake scholar open <库>`（如 `scholar open cnki`；只打印 URL，不打开浏览器） |
| 当前 IP 能否直连订阅库 | `westlake scholar campus`（信标探测，缓存 30 分钟） |
| CARSI 联盟资源目录（356 个） | `westlake scholar carsi [关键词] [--refresh]` |
| 校外登录某数据库（CARSI/统一密码） | `westlake scholar ensure`（Agent 主入口：会话活着零动作→验证码关时无头登录→必要时弹浏览器由本人输一次验证码；会话 cookie 全机共享）；`status` 查会话与验证码态 |
| 让别的 Agent 一气呵成用学术资源 | `westlake scholar ensure` 一条命令拿共享会话（~/.westlake_survival/scholar_cookies.json），之后 `scholar doi … -o` 直接带订阅通道下载 |
| 服务是否可达（选课组件/OPAC/打印/token/场馆座位入口） | `westlake probe` |
| 这套工具一共能干什么、哪些要账号 | `westlake webui serve` → `/capabilities`（或 `curl /api/capabilities`） |
| 前端接口有哪些、返回什么 | `/capabilities` 页底部「HTTP 接口」区（含实时样例） |
| 一步打开全部功能 | 裸跑 `westlake`（等价 `westlake go`：起 WebUI 并自动开浏览器；**首次启动直接落在「设置」页**） |

## 首次使用：用户走网页，终端留给 Agent

用户侧（2026-10-23 裁定：基本不用终端；2026-10-28 追加：网页是第一入口）：

1. **第一步就是看到网页**：双击仓库根的 `start.bat`（Windows）/ `start.command`（macOS），
   或运行裸命令 `westlake`——浏览器自动打开，本机还没配过账号时**直达 `/setup`**
   （配过则直达仪表盘；不想被打断的自动化用 `westlake --help` 或 `WESTLAKE_NO_WEBUI=1`）；
2. 在「设置」页填一次学号 + 统一密码；下面另有一行
   **Canvas 令牌（选填）**，可保存也可一键「清除令牌」；地图无账号，不再有地图密码；
   只想看公开功能的点「先看看公开功能」走 `/?skip=1`，不填也能用；
3. 页面当场显示账号是否接通，并明确区分「已验证并保存 / 未验证已保存」；
   保存后横幅自动消失，给「进首页」按钮。验证没通过也会落盘，不必重填。

Agent 侧：`westlake setup`（同一套验证与落盘，参数见 --help）。只管理令牌时可不带学号密码：
`westlake setup --canvas-token '<令牌>' --no-verify` 保存，
`westlake setup --clear-canvas-token` 删除本地令牌（Canvas 随即回退统一密码）。

一次输入的真实边界：教务 SIS 走统一身份认证（IAM OAuth2），填统一（校园门户）
密码即可；Canvas 同一套统一密码（无令牌自动回退 IAM CAS 会话）；打印系统是
另一套密码。公开功能无需任何账号；地图全公开（图片 + 720° 全景）。

**凭据是本机状态，不跨端同步**（2026-10-26 查明）：换机器、换系统用户、换
`WESTLAKE_HOME` 或换 Python 环境都要各自配一次；`westlake sso creds status`
报来源有无，可用来判断「到底存在哪」。

**凭据只存一份**（2026-10-27 实案）：持久存储只有两选一——系统钥匙串，或明文
`credentials.txt`。写入动作（`westlake setup` / `sso creds set`）会自动清掉另一份，
所以不会出现「钥匙串存着旧账号遮住正确文件」这种长期误报密码错的状态。
读取用 `cred_set`（进程内）或 `WESTLAKE_CREDENTIALS`（进程级）只影响当前进程，不落盘。
**登录报密码错时别反复试**——会累积 IAM 失败计数触发图形验证码（14h+ 不复位），
先 `sso creds status` 看凭据到底存在哪。

## 凭据前提（先判断再执行，缺凭据就换命令）

- **SIS 类**（`sis` / `sis-evals` / `profile` / `records` / `aid` / `pms jobs`）：需先 `westlake sso creds set` 写入学号密码，且**只在校园网/VPN 内可达**。
- **教学系统 AMS（`ams.westlake.edu.cn`）**：走 **IAM 统一认证**（同一套统一密码，`iam.login_for('https://ams.westlake.edu.cn/sso/login')`）；经典 CAS 不接这个 service（返回 Application Not Authorized），别套 Canvas 那套。会话缓存 8 小时（`~/.westlake_survival/ams_cookies.json`），页面层另加 2 分钟缓存。只读：课表/周次/菜单/通知；选课与学籍修改一律进系统做。详见 [docs/ams.md](../../../docs/ams.md)。
- **图书馆（2026-10-28 系统迁移，暂不可用）**：老阿法迪 OPAC `/opac/*` 整体下线（连根都 404），学校换成「阿法迪云 eLibrary」（内网 `172.16.10.223:8180/page/login.jsp`，**平台自有账号**；公网别名 `opac.westlake.edu.cn` 只剩首页快照、不反代 `/page/`）。`westlake lib search|loans` 会直接说明现状并退出、**不再尝试已失效的 CAS 登录**（反复失败有锁号风险）；WebUI 的「图书馆」页已按用户要求下线，别再去找这个页面。查书/借阅请让用户直接访问图书馆网站；接新平台需本人浏览器登录一次后重探接口，见 [docs/library_migration_2026-10-28.md](../../../docs/library_migration_2026-10-28.md)。
- **预约中心（`booking`）**：同一套统一密码，登录走预约中心自己的 OIDC（`booking.westlake.edu.cn/sso/oauth2`，隐式流取 access_token），`iam.login_for` 一步到位，无需另配令牌。**看到分类先别高兴**：接口对「没权限的分类」不报错、只返回空列表，判断能不能约要看 `booking types`（首页可见卡片）。
- **体育场馆/游泳（`sport`）**：独立正元系统 `sportvenue.westlake.edu.cn`，同一套统一密码走 IAM CAS（`client_id=tycgyy`），首次运行自动登录；每个请求带 `appId/nonce/timeStamp/sign` 签名（前端公开定值，非账号凭据）。只读：场景、场地、逐日可约、我的预约；**不做预约/取消**（下单涉及次卡支付，未接）。
- **预约类需求不是一套系统**（2026-10-27 审计，见 [docs/module_audit_2026-10-27.md](../../../docs/module_audit_2026-10-27.md)）：预约中心只覆盖自习室/研讨室/琴房等 17 类；**体育场馆/游泳**在独立的正元系统 `sportvenue.westlake.edu.cn`（登录已通，卡在服务端「表单规则未找到」，见 [docs/sportvenue_notes.md](../../../docs/sportvenue_notes.md)）；**图书馆座位**在 `seats.library.westlake.edu.cn`，它加载企业微信 JSSDK（`jwxwork`），属企业微信微应用，浏览器直连拿不到 `accessToken`；办事大厅还另有「场馆预约」`infoplus/form/CGYY` 与「资源预约」`ResourceReservation` 两个**流程表单**（发起即创建流程实例，属写操作，字段未探明）。
- **Canvas 类**（`canvas`）：优先令牌（`/setup` 保存、`WESTLAKE_CANVAS_TOKEN` 环境变量或 `~/.westlake_survival/canvas_token.txt` 首行）；**无令牌时自动回退统一认证**（IAM CAS 会话，2026-10-24 实测 REST API 认会话 Cookie）——配好教务统一密码即可用 Canvas，无需任何令牌。报 401 先怀疑「存了过期令牌抢在统一密码前面」：`westlake setup --clear-canvas-token` 或在 `/setup` 点「清除令牌」即可回退。
- **电子地图类**：无账号。`/map` 只放官网公开内容（校区地图图片 + 720° 全景链接 + 交通），按用户裁定 2026-10-24 已移除账号与数据集抓取体系。
- **无凭据照常可用**（官网公开数据，校外可直连）：`calendar` / `transit` / `context` / `digest` / `search` / `news` / `program` / `research` / `events` / `careers` / `faculty` / `campus` / `map` / `contact` / `pms stations` / `probe` / `cache`，以及 `scholar dbs|campus|doi|carsi|open`（学术库注册表、校园 IP 信标、DOI 解析、CARSI 目录、某库入口 URL——后两者离线也查得到快照，PDF 下载需校园网/VPN 或 OA 副本）。
- **学术资源（2026-10-24 实测）**：本校是 CARSI 联盟成员（`idp.westlake.edu.cn` Shibboleth IdP），统一密码可登录各出版社；校园网内出版社按 IP 认账（ScienceDirect 实测自动认证、Springer PDF 直下实测 200）。`scholar doi` 走「OA 副本（OpenAlex）→ 出版社 citation_pdf_url（校园 IP 订阅通道）」两级取全文；校外先 `scholar sso <库>` 建立联盟会话（Playwright profile 持久化，IAM 若弹图形验证码由本人在窗口输入一次）。
- 快速自检：`westlake sso creds status` 报来源有无（**绝不回显密码**）；持久存储只会有
  钥匙串或明文文件其中之一，写入时自动清掉另一份。

## 卡点判断：先归因，再谈能不能做（2026-10-27 复盘）

用户说某件事「做不了」时，**不要直接把它记成「系统不支持」**。先按五问定性：

1. **锚定**：我把这个需求绑到了某一个系统上吗？（「预约」= 预约中心 → 漏了 sportvenue、seats.library、CGYY 表单）
2. **时效**：我依据的是历史通知/旧记录吗？（8 月通知 ≠ 现在的开放状态）
3. **占位符**：仓库/页面上有没有「外链、勿动、另一套系统、暂未接入」这类注记？它们是入口线索，不是结论。
4. **搜不到**：我是「确认不存在」还是「没搜到」？（DNS 词表漏了 sportvenue；Wayback 缓存只有 11 个域名；单级词表找不到 `seats.library`）
5. **问人**：卡住超过一轮，就别再猜——用户知道自己平时从哪个 App/入口办。

判定前先跑这三条，都是只读、几十秒：

```bash
westlake probe          # 选课组件授权/OPAC/打印/场馆座位入口——已有的「堵点仪器」
westlake hosts list     # 清单含证据源合并结果；新发现的主机在这里出现
westlake affairs apps 预约   # 办事大厅 176 个应用；外链应用常指向真实系统
```

**卡住就写三栏表**，第三栏通常就是用户：

| 我知道 | 我不知道 | 谁知道 |
| --- | --- | --- |
| 已实测的接口、状态码、错误文案 | 未验证的猜测 | 用户 / 信息技术中心 / 总务部 |

归类只有四种，结论里必须写明是哪一种：

- **真做不了**：权限/网络/服务端缺失（例：sportvenue 表单规则未找到、OPAC 整个 webapp 404、HPC 成果库断、SIS 选课车「您无权访问该页面」）。
- **没建工具**：接口通、只是我们没写（例：自习室预约、`eval` 学工平台）。
- **逆向没做完**：链路只通一半（例：图书馆座位需企业微信授权）。
- **我判断错了**：旧结论过期或锚定单一系统（例：任务中心「登录失败」已不成立；~~选课组件实际已授权~~ 2026-10-27 推翻——组件页正文是「您无权访问该页面」，早期 probe 只认英文 `not authorized` 才误报已授权）。

对应清单见 [docs/module_audit_2026-10-27.md](../../../docs/module_audit_2026-10-27.md)；新增系统先登记进
`discovery.EVIDENCE_HOSTS`，别只写在对话里。

### 模块体检（改任何解析层前后各跑一次）

```bash
python tools/module_smoke.py            # 51 条只读命令，判定 OK/EMPTY/AUTH/FAIL/MISSING
python tools/module_smoke.py sis canvas # 只跑匹配模块
```

基线（2026-10-27）：OK 44 / EMPTY 7 / FAIL 3。新增模块**必须**在
`tools/module_smoke.py` 的 `COMMANDS` 里登记一条只读命令，否则它永远不会被体检。
第二轮查出的缺陷与修法见 [docs/module_audit_round2_2026-10-27.md](../../../docs/module_audit_round2_2026-10-27.md)：
SIS 改中文后 9 条命令静默空、Canvas 只取 7 天内截止、`sites`/`search` 静默降级。

**并发审计的硬规则（2026-10-27 踩过）**：同一账号同时最多 2 路登录；看到
`4333 验证码或登录名为空` 立即停手，不重试（重试只给失败计数续期）；
`verifyCodeIsNeed` 返回 None ≠ 没被风控，`authExecute` 照样会拒。

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
westlake events detail <URL>                 # URL 不在列表输出里：从网页复制，或 Python API events.upcoming() 的 .url
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
westlake scholar open cnki                    # 某库直达/CARSI 入口 URL（只打印，不开浏览器）
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
westlake sis cart                             # 选课车（只读；未授权时明确报「您无权访问该页面」）
westlake sis ical --out schedule.ics
westlake sis-evals list --pending
westlake profile info                        # info|academic|extended
westlake records dorm                        # 共 14 个子命令：dorm|leave|honors|volunteer|vol-history|practice|discipline|second-class|advisor|other-apps|appointments|registration|leaving-check|source-info
westlake aid loans                           # 共 7 个子命令：loans|jobs|claim|outbound|exchange|orgs|activities
westlake aid orgs --wiki                     # 社团目录 + 一句话简介（内置数据，改写自 WikiLake，见 docs/clubwiki.md）
westlake wiki list --cat clubs               # WikiLake 校园百科（学生自建）：目录 / search 关键词 [--deep] / page 条目名，见 docs/wikilake.md
westlake wiki search 班车
westlake wiki page 音游社
westlake ams status                        # 教学系统：学期/周次 + 今天的课
westlake ams schedule --json               # 本周课程（去重后）结构化输出
westlake ams menus                         # 学籍/选导师/选课/我的课表 入口
westlake lib search 数据结构 --page 1    # 2026-10-28 起系统迁移，暂不可用（会说明现状并退出）
westlake lib loans                        # 同上；不再尝试已失效的 CAS 登录
westlake pms jobs
```

门户（统一密码，取门户个人卡片与 AI 助手入口）：

```bash
westlake portal cards                        # 未读邮件 / 在借图书 / 待办计数
westlake portal chatbot                      # AI 助手聊天入口 URL
```

场馆（体育/游泳，统一密码 + 校园网；只读）：

```bash
westlake sport scenes                                   # 15 个场景（球场/次卡）
westlake sport sites 游泳次卡 [--date 2026-10-28]        # 当日场地与可约状态
westlake sport sites C16羽毛球场 --date 2026-10-28
westlake sport days 游泳次卡 游泳场次 --start 2026-10-28 --end 2026-11-03
westlake sport mine [--history]                          # 我的场馆预约
```

就业服务网深列表/详情（campus/jobfair/teachin 需统一密码自动登录；news 公开、
登录被风控挡住时自动降级匿名；只读，投递等动作由本人完成）：

```bash
westlake career deep --kind campus --page 1    # campus|jobfair|teachin|news 分页全量
westlake career deep --kind news --page 1      # news=毕业之后+生源速览两个栏目合并
westlake career detail 1129108                 # 详情正文（REF 也可用列表输出的 URL / news aid、tag）
```

需 Canvas 访问（令牌或统一密码会话）：

```bash
westlake canvas courses
westlake canvas deadlines --limit 10
westlake canvas exams --days 30
westlake canvas assignments --course 概率论        # 列作业（课程给 id 或名称关键词均可）
westlake canvas assignment-info --course 概率论 --assignment Assignment5           # 描述 + 描述内附件
westlake canvas assignment-info --course 概率论 --assignment Assignment5 --download ./资料   # 顺带下载附件
westlake canvas files --course 概率论 --match 作业 --download ./资料                # 文件区筛选下载
westlake canvas discussions --course 概率论        # 讨论主题（未读 / 回复数 / 时间）
westlake canvas announcements --course 概率论      # 课程公告
westlake canvas discussion --course 马原 --topic 什么是空间   # 主题正文 + 附件
westlake canvas entries --course 马原 --topic 4123 --limit 20  # 回帖列表
westlake canvas reply --course 马原 --topic 4123 --text "……"  # 发回帖（写操作）
westlake canvas inbox --limit 20 [--unread]        # 收件箱会话 + 未读数（打开单个会话会标为已读）
westlake canvas conversation 2041 --download ./资料 # 会话全文 + 附件下载
westlake canvas send --conversation 2041 --text "……"  # 回私信（写操作）
westlake canvas submit --course 概率论 --assignment 作业3 --file hw3.pdf   # 交作业
westlake canvas submit --course 概率论 --assignment 作业3 --file hw3.pdf --dry-run  # 只预检
westlake canvas submit --course 概率论 --assignment 简介 --text "……"      # 文本提交
westlake canvas submission --course 概率论 --assignment 作业3              # 查提交状态
```

OneDrive/SharePoint 分享（教师讲义）：

```bash
westlake share add 2183-lecture-notes https://westlakeu-my.sharepoint.com/:f:/g/personal/…   # 登记一次
westlake share saved                                       # 已登记的分享与链接
westlake share remove <名字>                               # 删除已登记的分享
westlake share files --name 2183-lecture-notes             # 列文件（大小 / 修改时间 / 子目录）
westlake share files --name 2180-lab-resources --path "Advanced Labs"   # 子目录
westlake share download --name 2183-lecture-notes --match day01 --out ./讲义   # 只下命中项
```

`submit` 是写操作：默认先预检并弹确认，`--yes` 跳过确认，`--dry-run` 只预检不提交；课程/作业都接受 id 或名称关键词（子串匹配，唯一命中才执行；匹配不到就先用 `courses`/`assignments` 查全名——如课程叫「物理学实验 Ⅱ」，搜「物理实验」搜不到；命中多个会列出候选）。提交链路已真机验证（2026-10-15 真交 Lab 5 成功：西湖 Canvas 禁学生写课程文件区，包内自动退回本人文件区上传再提交，效果相同）。

`assignments` 里没有截止时间、提交类型为 `none` 的条目（ClassParticipation、Quiz 等）多为课堂记录，不一定需要动手；要确认就看 `canvas assignment-info` 的描述。

课程资料**按需从 Canvas 现拉，不依赖任何本地镜像库**：不带 `--download` 的命令只读元数据、不写盘；给 `--download <目录>` 才落文件，且只下当前命中的那门课/那个作业/那个讨论。不要为了一次查询去同步整门课或整学期——单个课件通常几十 KB 到几 MB。老师另行通过 OneDrive/SharePoint 分享的讲义走 `westlake share`（见上表与下方示例）：分享链接设为「组织内任何人可查看」时免账号读取；只对特定人开放的链接会报 403，只能请分享者放开权限。

## Python API 直用（需要结构化数据时）

前提：用与 `westlake` 命令同一个解释器（`pip show westlake-survival` 可查安装位置）。直接 `import westlake_survival` 报 ModuleNotFoundError，通常只是没装进当前解释器，换到装了包的那个即可。

```python
from westlake_survival.context import snapshot, Level
from westlake_survival.transit import transit

print(snapshot(Level.TERSE).to_str())                  # 今日快照纯文本
for table, hhmm in transit().next_departures(limit=3): # 下一批班车
    print(hhmm, table.campus.value)
```

```python
from westlake_survival import sportvenue  # 场馆：统一密码 + 校园网

for scene in sportvenue.scenes():                       # 15 个场景
    print(scene.name, scene.uuid)
swim = sportvenue.find_scene("游泳")
for site in sportvenue.sites(swim):                     # 当日场地（缺省明天）
    print(site.name, site.bookable, site.reason)        # 不可约时给服务端原话
for day in sportvenue.days(site, start="2026-10-28", end="2026-11-03"):
    print(day.day, day.bookable, day.reason)
```

```python
from westlake_survival.sis import get_schedule, grades  # 需凭据 + 校园网

for s in get_schedule():
    print(s.title, s.weekday, s.start_time, s.room)
for g in grades():                                      # 不计算 GPA（无官方换算口径）
    print(g.term, g.course_code, g.course_title, g.grade)
```

```python
from westlake_survival.canvas import canvas                       # 令牌或统一密码会话
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

`CanvasClient` 的其余方法（CLI 同名命令已覆盖大部分，需要结构化数据时直用）：

| 方法 | 返回 / 作用 |
| --- | --- |
| `me()` / `list_courses()` / `get_course(id)` | 当前用户 / 课程列表 / 单课程 |
| `find_course(关键词)` / `find_assignment(cid, 关键词)` | 名称或 id 唯一定位（零命中 NotFound、多命中列候选） |
| `todo(limit)` | 待办 `TodoItem`（课程、类型、截止，北京时间） |
| `modules(course_id)` | 模块与条目 `[{name, count, items}]` |
| `discussions(course_id)` | 讨论主题 `[{id, title, unread, replies, posted, url}]` |
| `discussion_topic(cid, tid)` / `discussion_entries(cid, tid)` | 主题正文与附件 / 回帖列表 |
| `find_topic(cid, 关键词)` | 主题 id 或标题唯一定位 |
| `list_announcements(course_id)` | 课程公告 `Announcement` |
| `conversations(limit)` / `unread_count()` | 收件箱会话（时间已换算） / 未读数 |
| `conversation(id)` | 会话全文与附件 `{subject, participants, messages}` |
| `reply_to_discussion(cid, tid, text)` / `reply_conversation(id, body)` | 发回帖 / 回私信（写操作） |
| `get_assignment(cid, aid)` | 单作业详情（描述、评分细则 rubric、允许扩展名、提交次数） |
| `assignment_attachments(cid, aid)` | 从描述抽附件 `[{file_id, name, size}]` |
| `list_files(course_id)` / `file_info(file_id)` | 课程文件清单 / 单文件元数据 |
| `download_file(file_id, dest)` | 流式下载（签名地址，不带 token） |
| `submit_assignment(…)` / `get_submission(cid, aid)` | 提交（干跑/真交） / 回读提交状态 |

**题目文件可能挂在三处**：作业描述里的文件链接（`assignment-info` 已抽取）、课程文件区（`canvas files`）、模块条目（`canvas modules`）。描述里没有附件不代表没有题目文件，另两处要一起看。

## MCP 备选通道

本包自带零依赖 stdio MCP 服务器，暴露 65 个工具（学业 `sis_schedule`/`sis_grades`/`sis_exams`/`sis_cart`/`sis_evals_pending`/`sis_second_class`/`sis_advisor`/`sis_other_applications` + records/aid 类，就业 `career_latest`/`career_deep`/`career_detail`，校历班车 `calendar_today`/`calendar_week`/`transit_next`，内容 `news_latest`/`events_upcoming`/`research_latest`/`site_search`/`faculty_search`/`affairs_apps`，百科 `wiki_search`/`wiki_page`（学生自建 WikiLake，只读），培养 `program_*` 六个，校园 `campus_dining`/`campus_housing`/`campus_map`/`contact_info`/`context_snapshot`，学术 `scholar_databases`/`scholar_resolve_doi`/`scholar_campus`，作业与课程 `canvas_deadlines`/`canvas_todo`/`canvas_submit`/`canvas_files`/`canvas_assignment_info`/`canvas_discussions`/`canvas_announcements`/`canvas_inbox`/`canvas_conversation`/`canvas_discussion_entries`，分享 `share_files`，场馆 `sport_scenes`/`sport_sites`/`sport_days`/`sport_reservations`）。写操作（提交作业、回帖、回私信）只在 CLI 提供，MCP 侧保留 `canvas_submit` 一个写工具；所有写入都要显式确认。客户端配置：

```json
{"mcpServers": {"westlake": {"command": "westlake-mcp"}}}
```

若 `westlake-mcp` 不在 PATH：`"command": "python", "args": ["-m", "westlake_survival.mcp_server"]`。**选型**：要工具自动发现与结构化返回选 MCP；要轻量、零配置、能直接用自然语言描述命令选本 skill。

## Agent 行为守则

- **网络一律直连（库层已内置）**：所有 HTTP 会话默认 `trust_env=False`（无视 `HTTP_PROXY/HTTPS_PROXY` 直连），**Agent 自己临时写脚本抓校园站点时也必须显式直连**（`requests` 传 `trust_env=False`，或复用 `westlake_survival.discovery.direct_session()`）；唯一例外是 HPC 成果库（172.16.75.35:8007）的代理兜底通道。诊断「校内服务连不上」时先排除代理劫持（对照：直连 vs 代理各试一次），再怀疑防火墙/网段 ACL。
- **默认只读，写操作都要当轮明确指令**：查询/导出命令可自由执行；写操作仅限五条——交作业 `canvas submit`（MCP 的 `canvas_submit`）、讨论回帖 `canvas reply`、私信回复 `canvas send`、预约场地 `booking book`、取消预约 `booking cancel`。三者都只凭用户当轮明确给出的课程/会话、对象与内容执行，不尝试选课、抢课、删除等其他写操作，不构造未文档化的请求。
- **交作业三步走**：①预检 `--dry-run`（作业未锁定、类型允许、文件可读）；②提交（用户点名文件即视为授权）；③回读 `canvas submission` 核验（状态 submitted、附件文件名、未迟交）确认后才报完成。已评分（graded）的作业技术上可重交但默认不碰，除非用户明确要求改交。
- **回帖与私信同样先确认**：`canvas reply` / `canvas send` 默认打印将发送的正文并等确认，`--yes` 才直接发；发完回读（`canvas entries` / `canvas conversation`）核对内容确实落地。不可回复的会话（`cannot_reply`）直接拒绝，不绕过。
- **写作业内容先看课程资料**：动笔前先看作业描述与附件（`canvas assignment-info`），再看课程文件区（`canvas files`）与模块条目（`canvas modules`）；实验报告参照本人历史提交物的格式惯例。不要假定资料在某个固定本地路径。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不在输出中回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的「有 / 无」。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等属个人隐私，输出给第三方前默认做脱敏/摘要提示，并提醒用户自行确认是否适合分享。
- **失败降级**：`OffCampusError` = 目标系统仅校园网/VPN 可达，提示用户连接 <https://vpn.westlake.edu.cn/>；`AuthError` = 凭据缺失或失效，提示 `westlake sso creds set`；Canvas 报错先看是否存了过期令牌（`westlake setup --clear-canvas-token` 回退统一密码），再考虑配置 `WESTLAKE_CANVAS_TOKEN`。命令失败时如实转述错误，不臆造数据。