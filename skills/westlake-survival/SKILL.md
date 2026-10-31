---
name: westlake-survival
description: 西湖大学校园服务聚合工具（学业/教学/科研/生活/办事/信息六域）。学业：课表（SIS 与教学系统 AMS 两套）、成绩、考试安排、评教、第二课堂、个人信息/学籍/住宿/荣誉/志愿/资助/社团；Canvas：课程、作业截止、考试测验、作业详情与题目附件（含评分细则）、课程文件下载、讨论区与公告、收件箱，以及交作业/回帖/回私信三类写操作；学术科研：订阅数据库清单、CARSI 校外登录（westlake scholar ensure 自动建立会话）、DOI→PDF 论文全文下载、大型仪器共享检索（冷冻电镜/质谱/核磁）、HPC 集群队列与免费 AI 对话（westlake hpc chat，deepseek/glm/qwen）、科研进展、导师名录、报销与科研经费制度；就业：招聘岗位、招聘会、宣讲会；生活：校历周次与假期、班车时刻、食堂咖啡、公寓、校区地图与全景、自助打印、图书馆借阅、预约中心场地预约（研讨室/研习仓逐日空闲与预约、取消；体育场馆/游泳与图书馆座位在独立系统，入口与对照见文档）；办事：办事大厅目录与表单直达、我的待办、门户个人卡片与官方 AI 办事问答（westlake portal ask）；信息：新闻、讲座活动、学院动态、全站搜索、93 项服务注册表与在线普查。适用于西湖大学相关的查询或操作需求（包括查/交作业、考试安排、放假校历、班车时刻、论文全文获取、校外数据库访问、打印网点、经费制度、讲座待办、教师信息、档案记录与服务探测等）。不确定命令归属时，可先运行 westlake find <关键词> 检索（支持「论文」「借书」「放假」「大模型」「仪器」等关键词）。
---

# 西湖大学服务工具包（westlake-survival）

汇总西湖大学常用校园服务，提供命令行工具、Python API 与 MCP 服务器。**默认只读**：写操作严格受限为五项，且均须凭用户明确指令执行（`canvas submit` 作业提交、`canvas reply` 讨论回帖、`canvas send` 私信发送、`booking book` 场地预约、`booking cancel` 取消预约）。上述写操作统一经由 `consequence.py` 确认拦截（缺少 `--yes` 参数时打印结构化风险描述并以状态码 1 退出，`--dry-run` 仅作预检，不进行交互式询问）；不包含选课、抢课等其他写操作。

本文只放路由与行为规则；**完整命令示例、Python API 方法表、MCP 工具清单在 [docs/skill_reference.md](../../docs/skill_reference.md)**，各系统深挖见 docs/ 对应文档（按需再读，不必全量加载）。

## 环境自检（Agent 接入规范）

建议优先运行 `westlake doctor`（不在 PATH 时使用 `python -m westlake_survival doctor`；支持 `--json` 输出）。检查项覆盖 Python 解释器、包安装、命令路径一致性、依赖完整性、账号配置及网络状态；退出码 0 表示通过，1 表示存在缺失项，全部通过后再开展后续工作。

- **按需补齐依赖**（仅限 Python 依赖）：源码环境执行 `pip install -e .`，独立环境执行 `pip install westlake-survival`（Flask 与 keyring 属于基础依赖，包含 WebUI 与凭据加密存储）。`.[browser]`（Playwright 及配套 Chromium）为**可选增强**：未安装时 doctor 仅提示 warning，讲义解析、子站深度渲染与 CARSI 校外 SSO 自动降级，其余功能正常可用。无桌面 Linux 环境下，若无法获取系统钥匙串后端将降级至本地配置文件并提示 warning；Playwright 缺少系统依赖时可执行 `playwright install-deps chromium` 补齐。
- **解释器一致性**：确保 `westlake` 命令、`python -m westlake_survival` 与调用脚本使用同一个 Python 环境，避免环境错位导致模块无法导入。排查方式：`which westlake`（macOS/Linux）或 `where westlake`（Windows），结合 `pip show westlake-survival` 核对路径；若存在偏差，统一使用 `python -m westlake_survival` 调用。
- **账号配置规范**：当 doctor 提示「校园账号未配置」时，引导用户运行 `westlake`（或对应平台启动脚本），在本地网页「设置」页面自行填写，Agent 严禁索取凭据或代填。测试与沙箱隔离可配置临时 `WESTLAKE_HOME` 或设置 `WESTLAKE_NO_KEYRING=1`，此时将完全跳过系统钥匙串读写。
- **网络直连**：网络请求默认直连，忽略 `HTTP_PROXY/HTTPS_PROXY` 代理配置；校外访问教务系统或 Canvas 需连入校园网或开启 VPN，可先执行 `westlake vpn status` 确认。

## 能力路由

不确定归哪条命令先 `westlake find <需求关键词>`（口语可命中）。下表命令均省略 `westlake ` 前缀：

| 用户想问 | 命令 |
| --- | --- |
| 环境不对 / 装了用不了 / 不知道归哪条 | `doctor` / `find <关键词>` |
| 今天几号 / 第几周 / 校历事件 / 学期 | `calendar today` / `week N` / `events` |
| 下一班校车 / 班车时刻 / 课表班车 ICS | `transit next` / `table` / `transit ical`（网页 /ical 一键复制） |
| 当前状态快照 / 今日快报 | `context` / `digest` |
| SIS 课表 / 成绩 / 考试 / 选课车 / ICS | `sis schedule` / `grades` / `exams` / `cart` / `sis ical`；周网格+冲突检测 `sis grid`（只读；选课窗口开可并入选课车节次预检） |
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
| 食堂 / 公寓 / 校园生活网点 / 电话 / 地图 | `campus dining` / `housing` / `campus services`（超市/快递/干洗/理发/打印/银行）/ `contact phones` / `map` |
| 什么事在哪儿办 / 表单直达 / 我的待办 | `affairs apps [关键词]`（带直达URL）/ `affairs app <名称>` / `affairs links` / `todo list\|doing` |
| 门户个人卡片 / 官方 AI 办事问答 | `portal cards` / `portal ask <问题>`（西湖AI问答权威答疑）/ `portal chatbot` |
| 打印网点 / 我的打印任务 | `pms stations` / `jobs` |
| 图书馆书目检索 / 我的在借图书 | `lib search <关键词>`（新版阿法迪云平台，免鉴权公开查）/ `lib loans`（在借图书与应还日期） |
| 场地预约：分类 / 房间 / 哪天能约 / 空闲时段 | `booking types` / `list --type 图书馆` / `days <房间> --start … --end …` / `slots <房间> --date …` |
| 预约 / 取消预约（写操作）/ 我的预约 | `booking book`（`--dry-run` 可预检）/ `cancel <预约号> --reason …` / `mine` |
| 体育场馆 / 游泳场次（独立正元系统，只读） | `sport scenes` / `sites <场景> [--date]` / `days <场景> <场地>` / `mine` |
| 预约类需求为什么约不了 / 从哪进 | `probe` + `affairs apps 预约`；四套系统对照 docs/module_audit_2026-10-27.md |
| HPC 集群 / 免费大模型对话 / 镜像站 | `hpc overview` / `hpc chat <内容>`（调用校内GPU集群）/ `hpc sync-key` / `mirrors` / `finance sections` |
| 大型科研仪器检索（电镜/质谱/核磁/地点） | `instrument search <关键词>` / `instrument list`（地点/联系人/电话/预约入口） |
| 服务是否可达 / 服务全景普查 | `probe` / `probe scan [--full]`（网页 /services、/capabilities） |
| VPN 登录 / 状态 / 隧道资源 | `vpn login` / `status` / `resources` |
| 启动本地完整服务 | 裸跑 `westlake`（起 WebUI 自动开浏览器，未配账号直达 /setup） |

## 用户入口（WebUI）

用户可通过启动脚本或运行 `westlake` 打开本地界面：初次运行若未配置账号会自动跳转至 `/setup`，由用户录入统一身份认证凭据（Canvas 令牌选填，支持独立清除）。验证通过后进入仪表盘。密码录入以本地网页表单为准，终端默认不提示输入（无图形环境可使用 `westlake setup --terminal`）；自动化测试支持指定参数。设置 `WESTLAKE_NO_WEBUI=1` 可禁用浏览器自动打开。统一身份认证适用于 SIS、Canvas、AMS、自助打印、场地预约、校内门户及体育场馆。

## 凭据前提（先判断再执行，缺凭据就换命令）

- **SIS 类**（`sis`/`sis-evals`/`profile`/`records`/`aid`/`pms jobs`）：先 `westlake sso creds set` 写学号密码，且只在校园网/VPN 内可达。
- **AMS**：同一套统一密码走 IAM 统一认证（经典 CAS 不接该 service）；会话缓存 8h；只读，选课学籍修改进系统做。见 docs/ams.md。
- **Canvas**：优先令牌（/setup、`WESTLAKE_CANVAS_TOKEN`、`~/.westlake_survival/canvas_token.txt`）；**无令牌自动回退统一密码会话**。报 401 先怀疑存了过期令牌：`westlake setup --clear-canvas-token` 回退统一密码。
- **预约中心**：统一密码 OIDC 自动登录；接口对没权限的分类只返回空列表，能不能约看 `booking types`。
- **sport**：统一密码 IAM CAS 自动登录；只读不做预约（下单涉次卡支付未接）。
- **无凭据照常可用**：`calendar`/`transit`/`context`/`digest`/`search`/`news`/`program`/`research`/`events`/`careers`/`faculty`/`campus`/`map`/`contact`/`pms stations`/`probe`/`cache` 与 `scholar dbs|campus|doi|carsi|open`。
- **凭据单一存储**：系统钥匙串或本地配置文件二选一，写入时自动清理另一份；`sso creds status` 仅报告凭据来源是否存在。若登录提示密码错误切勿反复重试，连续失败将触发统一身份认证验证码锁定。凭据属于本机状态，环境变更后需重新配置。

## 问题排查与功能归因

遇到功能不可用或查询未命中时，先厘清系统边界与当前状态：① 多系统交叉（例如场地预约分散在预约中心、体育场馆与图书馆座位系统）；② 时效性确认（通知或规则是否已有调整）；③ 接口与占位状态甄别；④ 检索范围是否受限；⑤ 必要时核对常规人工访问路径。

常规排查命令：`probe`、`hosts list`、`affairs apps 预约`。归因通常属于四类情况：权限/网络/服务端客观受限、尚未接入对应工具、接口解析待完善、或命令调用方式有误。可参考 docs/module_audit_2026-10-27.md 审计对照表；新发现系统应登记至 `discovery.EVIDENCE_HOSTS`。

修改解析逻辑前后，均须运行 `python tools/module_smoke.py` 验证；新增模块须在该测试脚本中登记只读测试命令。登录并发控制：同一账号并发登录不应超过 2 路；若捕获 `4333 验证码或登录名为空` 异常，须立即中止重试。

## Agent 行为守则

- **网络直连规范**：所有网络会话默认设置 `trust_env=False`；Agent 自行编写脚本访问校内站点时亦须显式直连（`requests` 传入 `trust_env=False`，或复用 `westlake_survival.discovery.direct_session()`）。排查网络连通性时优先确认是否存在代理冲突。
- **默认只读与写操作确认**：写操作严格受限于 `canvas submit`/`reply`/`send` 以及 `booking book`/`cancel`。统一经过 consequence.py 确认拦截：缺少 `--yes` 时打印结构化风险描述并以退出码 1 终止，获取用户明确指令后再添加 `--yes`；严禁构造未文档化的写操作请求。
- **Canvas 作业提交规范**：① 使用 `--dry-run` 预检提交内容；② 获得用户明确指令后通过 `--yes` 执行提交；③ 使用 `canvas submission` 回查提交状态与附件信息，确认无误后完成。已评分作业默认不执行二次提交。
- **回帖与私信**：`canvas reply`/`send` 未 `--yes` 会打印风险描述退出；凭用户当轮指令传 `--yes` 发送；发完回读核对落地；`cannot_reply` 的会话直接拒绝。
- **写作业内容先看课程资料**：动笔前看 `assignment-info`（描述与附件）、`files`、`modules`——题目文件可能在三处任一处，描述里没有不代表没有。不要假定资料在固定本地路径。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的有无。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等输出给第三方前默认脱敏/摘要提示。
- **失败降级**：`OffCampusError`=需校园网/VPN（<https://vpn.westlake.edu.cn/>）；`AuthError`=凭据缺失/失效（`westlake sso creds set`）；命令失败如实转述错误，不臆造数据。
- **回帖与私信**：`canvas reply`/`send` 未 `--yes` 会打印风险描述退出；凭用户当轮指令传 `--yes` 发送；发完回读核对落地；`cannot_reply` 的会话直接拒绝。
- **写作业内容先看课程资料**：动笔前看 `assignment-info`（描述与附件）、`files`、`modules`——题目文件可能在三处任一处，描述里没有不代表没有。不要假定资料在固定本地路径。
- **绝不打印凭据/令牌**：不 `cat` `~/.westlake_survival/credentials.txt` 或 `canvas_token.txt`，不回显学号密码或 `WESTLAKE_CANVAS_TOKEN`；只看 `sso creds status` 的有无。
- **个人数据脱敏**：成绩、学籍、住宿、贷款等输出给第三方前默认脱敏/摘要提示。
- **失败降级**：`OffCampusError`=需校园网/VPN（<https://vpn.westlake.edu.cn/>）；`AuthError`=凭据缺失/失效（`westlake sso creds set`）；命令失败如实转述错误，不臆造数据。
