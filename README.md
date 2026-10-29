# westlake_survival

> 把西湖大学散落在数十个系统里的校园服务，收拢成**一条命令、一次调用、一个页面**。
>
> Python 库 · CLI · MCP 服务器 · 本地 WebUI —— 一套能力，四个入口，人与 AI 代理皆宜。

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-58839b)
![MCP](https://img.shields.io/badge/MCP-server-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-dd4a4a)

西湖大学的校园服务散落在 SIS、教学系统 AMS、Canvas、预约中心、门户、图书馆、体育场馆……各自为政的几十个系统里。**westlake_survival** 在 API 层面把它们逐一接通，收敛为一个工具包：

- **CLI**：`westlake` 一条命令覆盖查询与少量写操作；不确定归哪条，`westlake find <口语关键词>` 直接问（「论文」「借书」「放假」都能命中）。
- **本地 WebUI**：裸跑 `westlake`（或双击启动脚本）自动打开浏览器进仪表盘——30+ 页面，含账号配置；`/capabilities` 一页列出全部能力。
- **MCP 服务器**：`westlake-mcp` 一个进程，接给任何支持 MCP 的 AI 客户端。
- **Python 库**：`import westlake_survival` 拿结构化数据，[examples/](examples/) 有可直接跑的样例。

三条底线，先说清楚：

1. **默认只读**。写操作仅五条——交作业、讨论回帖、回私信、预约场地、取消预约——且都必须凭使用者当轮明确指令执行；不做选课、抢课，不绕过权限。
2. **凭据只存本机**。钥匙串优先、只存一份、不打印不提交、不跨机器同步；账号由本人在网页「设置」页填写，终端不问密码。见[凭据与隐私](#凭据与隐私)。
3. **无官方背书**。社区工具，结构参考 [sustech_survival](https://github.com/dumixthestpd/sustech_survival)，与西湖大学官方无关。

## 功能总览

| 领域 | 覆盖 | 需账号 |
| --- | --- | --- |
| 学业（SIS） | 课表、成绩、考试安排、选课车、评教、第二课堂成绩单、学籍异动、学业导师、课表 ICS | 统一密码 |
| 教学（AMS） | 另一套课表、教学周次、学籍与选课入口 | 统一密码 |
| Canvas | 课程、截止与测验、待办、模块、课程文件下载、讨论区、公告、收件箱、作业详情（题目附件＋评分细则）；交作业、回帖、回私信 | 令牌或统一密码 |
| 场地预约 | 17 类场地（自习室/研讨室/琴房/活动用房…）：分类、逐日可约、逐格空闲、我的预约、预约与取消 | 统一密码 |
| 体育场馆 | 场景、场地、逐日可约、我的预约（只读） | 统一密码 |
| 任务与门户 | 办事大厅目录、我的待办/进行中/抄送、门户个人卡片（未读邮件/在借/待办计数） | 统一密码 |
| 学术科研 | 订阅数据库注册表、CARSI 校外 SSO（`scholar ensure` 一条命令）、DOI→PDF 全文下载、科研进展、导师名录、HPC 集群、报销与经费制度 | 部分免账号 |
| 就业 | 招聘岗位、招聘会、宣讲会：最新＋深列表＋详情 | 免账号 |
| 培养方案 | 专业学分要求与课程表、课程体系、通识课目录、课程搜索 | 免账号 |
| 校园生活 | 校历周次与假期、班车时刻与 ICS、每日晨报快照（`context`/`digest`）、食堂咖啡、公寓、校区地图与 720° 全景、打印网点 | 免账号 |
| 讲义下载 | OneDrive/SharePoint 分享讲义免账号直读与下载（需 `[browser]` 可选增强） | 免账号 |
| 信息检索 | 官网全站搜索、新闻、讲座活动、学院动态、学生百科 WikiLake | 免账号 |
| 系统盘点 | 90+ 项服务注册表、子站在线普查、站点栏目、服务可达性、VPN 状态与隧道路由 | 免账号 |
| 图书馆 | 系统于 2026-10-28 迁移至「阿法迪云 eLibrary」，借阅查询暂不可用（[迁移说明](docs/library_migration_2026-10-28.md)） | — |

体育场馆与图书馆座位是独立系统，与预约中心的对照见 [docs/module_audit_2026-10-27.md](docs/module_audit_2026-10-27.md)；办事门户 `affairs portal` 服务端接口近期疑似变化、暂报错。个人档案类（学籍/住宿/荣誉/志愿/资助/社团）还有 20+ 条只读命令，`westlake find` 一查便知。

## 快速开始

**最省事**：双击仓库根目录的 `start.bat`（Windows）/ `start.command`（macOS），或终端 `./start.sh`（Linux）。首次运行自动装依赖，随后浏览器自动打开——没配过账号直达「设置」页，**本人**填一次学号与统一密码，验证通过自动进仪表盘；之后每次启动直达仪表盘。同一端口已有服务在跑时不重复启动，直接把浏览器指过去。

**终端等价**：

```bash
pip install -e .              # Flask 已是基础依赖，装完即有前端；锁版本用 requirements.txt
westlake                      # 起网页并开浏览器；脚本/自动化设 WESTLAKE_NO_WEBUI=1 关闭弹出
westlake calendar today       # 校历等公开功能无需账号
westlake --help
```

启动行为与首次配置的完整契约见 [docs/first_run.md](docs/first_run.md)。环境不对（装了却用不了、缺依赖、命令和解释器不同环境）先跑 `westlake doctor`：逐项体检解释器/依赖/账号/网络，缺什么给一条能直接抄的修复命令（[docs/doctor.md](docs/doctor.md)）。

## 配合 AI 代理使用（任何代理通用）

本仓库为代理而设计。三种接法按需选、可叠加：

1. **读 `AGENTS.md` 的代理**（ZCode、DSH、Codex、Claude Code、Cursor……）：clone 即用——根目录 [AGENTS.md](AGENTS.md) 已写明纪律、入口与验证方式，代理开会话自动读到；配好账号后直接差遣 `westlake` CLI。
2. **带技能（Skill）机制的代理**：技能文档在 [.zcode/skills/westlake-survival/SKILL.md](.zcode/skills/westlake-survival/SKILL.md)（ZCode 项目级已就位），其他代理把目录拷进自己的技能根即可被发现：
   ```bash
   git clone https://github.com/yizhang-dream/westlake_survival.git
   cp -r westlake_survival/.zcode/skills/westlake-survival ~/.agents/skills/   # 或 ~/.claude/skills/ 等你的代理的技能根
   ```
3. **MCP 客户端**：装包后注册 `westlake-mcp` 进程；配置片段与全套 MCP 工具清单见 [docs/skill_reference.md](docs/skill_reference.md)。

代理接手第一步永远是 **`westlake doctor`**（`--json` 便于程序判断）：全绿再干活；账号不由代理填，请使用者在网页「设置」页本人填写。

## 凭据与隐私

- **一个统一密码通吃**：SIS、Canvas、AMS、预约、体育、打印、门户都走西湖统一身份认证；Canvas 另兼容个人令牌，网页可存可清。
- **只存一份、只存本机**：钥匙串（Windows 凭据管理器 / macOS 钥匙串 / Linux Secret Service）优先；写文件即自动清钥匙串，反之亦然（[docs/credential_single_store.md](docs/credential_single_store.md)）。不跨机器、不跨系统用户同步。
- **密码只在网页表单里敲**：终端默认不问密码（SSH 等无图形环境才 `westlake setup --terminal`）；做隔离测试设 `WESTLAKE_HOME` 或 `WESTLAKE_NO_KEYRING`，任一成立即沙箱。
- **默认直连**：全部会话 `trust_env=False`，无视 `HTTP_PROXY/HTTPS_PROXY`——校园站点经系统代理常 502/超时；外部脚本复用请走 `westlake_survival.discovery.direct_session()`。
- 校外访问教务/Canvas 需校园网或 VPN：`westlake vpn status` 查状态。

## 验证（端到端）

本仓库不维护单元测试，功能验证一律端到端真跑：

```bash
python tools/module_smoke.py   # 全部只读 CLI 逐条真跑，出 OK/EMPTY/AUTH/FAIL 体检表
python tools/webui_smoke.py    # 进程内起真实 Flask 服务，逐页 GET 断言 200
python tools/pii_scan.py       # 提交前扫真实学号等个人信息
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/first_run.md](docs/first_run.md) | 启动行为与首次配置契约 |
| [docs/doctor.md](docs/doctor.md) | 环境自检逐项说明 |
| [docs/skill_reference.md](docs/skill_reference.md) | 命令示例、Python API 方法表、MCP 注册 |
| [docs/credential_single_store.md](docs/credential_single_store.md) | 「凭据只存一份」的设计与实现 |
| [docs/ams.md](docs/ams.md) / [docs/sportvenue_notes.md](docs/sportvenue_notes.md) / [docs/wikilake.md](docs/wikilake.md) / [docs/clubwiki.md](docs/clubwiki.md) | 各系统深挖注记 |
| [docs/library_migration_2026-10-28.md](docs/library_migration_2026-10-28.md) | 图书馆系统迁移说明 |
| [docs/module_audit_2026-10-27.md](docs/module_audit_2026-10-27.md) | 各模块「做不了」归因审计 |

## 许可与致谢

- 许可：[PolyForm Noncommercial 1.0.0](LICENSE)，仅限非商业用途并保留署名。
- 致谢：结构参考 [sustech_survival](https://github.com/dumixthestpd/sustech_survival)；社团简介改写自学生自建百科 WikiLake 并逐条附原文链接（[docs/clubwiki.md](docs/clubwiki.md)）。
- 本项目为社区工具，无西湖大学官方背书；仅访问使用者本人有权的数据。
