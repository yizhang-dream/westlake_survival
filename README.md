[English](README_en.md) | 简体中文

# westlake_survival

> 面向西湖大学师生的校园服务聚合工具包与开发套件。
>
> 提供 Python 库、命令行工具（CLI）、本地 Web 仪表盘与 MCP 服务端，兼顾日常使用与自动化接入。
>
> 📚 在线文档：https://yizhang-dream.github.io/westlake_survival/

![Docs](https://img.shields.io/badge/docs-online-8957e5)

![PyPI](https://img.shields.io/pypi/v/westlake-survival)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-58839b)
![MCP](https://img.shields.io/badge/MCP-server-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-dd4a4a)

西湖大学的校园服务分散在 SIS、教学系统 AMS、Canvas、场地预约、校内门户、体育场馆等多个系统中。**westlake_survival** 在 API 层面进行整合，收敛为统一的工具包与开发接口：

- **Python 库（进程内 API）**：安装 `westlake-survival` 后直接 `import westlake_survival` 获取全量结构化数据，适合 Python 脚本与代码执行环境；[examples/](examples/) 提供了可直接运行的示例。
- **CLI**：`westlake` 提供覆盖全功能的命令行入口；若不确定具体子命令，可使用 `westlake find <关键词>` 检索（支持「论文」「借书」「放假」等关键词）。
- **本地 WebUI**：运行 `westlake`（或双击启动脚本）自动启动本地服务并打开浏览器仪表盘，包含账号配置与 30 余个功能页面；可在 `/capabilities` 查看完整能力清单。
- **MCP 服务器**：提供 `westlake-mcp`，便于仅支持 Tool Call 的客户端（如 Claude Desktop、Cursor 聊天等）接入；具备终端环境的 Agent 直接调用 CLI 或 Python 库即可。

核心设计原则：

1. **默认只读与受控写操作**。写操作严格收敛在安全白名单内（Canvas 作业提交/回帖/私信/课程收藏/个人云盘上传/待办归档、联创文印云上传/作业取消、场地预约/取消、图书馆在借续借、日历导出），统一经由 `consequence.py` 事务门拦截并生成 Action Card（事务预览卡片与单次确认 Ticket）；不提供选课、抢课功能，不绕过权限系统。
2. **离线优先与优雅降级**。课表、校历周次、班车时刻表等低频数据全面走 SWR（Stale-While-Revalidate）架构，支持 `--offline` 离线快照直出，断网或无校内 VPN 依然秒级查阅。
3. **凭据仅存本地**。优先采用系统钥匙串并保持单一持久化存储，不打印、不提交、不跨设备同步；账号信息由使用者在本地网页「设置」页面录入，终端默认不提示输入明文密码。详见[凭据与隐私](#凭据与隐私)。
4. **无官方背书**。本项目为开源社区工具，项目结构参考 [sustech_survival](https://github.com/dumixthestpd/sustech_survival)，与西湖大学官方无关。

## 功能总览

| 领域 | 覆盖 | 需账号 |
| --- | --- | --- |
| 学业（SIS） | 课表、成绩、考试安排、选课车、评教、第二课堂成绩单、学籍异动、学业导师、课表 ICS | 统一密码 |
| 教学（AMS） | 另一套课表、教学周次、学籍与选课入口 | 统一密码 |
| Canvas | 课程、截止与测验、待办、模块、课程文件下载、讨论区、公告、收件箱、作业详情（题目附件＋评分细则）；交作业、回帖、回私信、课程收藏置顶 | 令牌或统一密码 |
| 场地预约 | 17 类场地（自习室/研讨室/琴房/活动用房…）：空闲时段复合推荐求解（`booking recommend`）、分类、逐日可约、逐格空闲、我的预约、预约与取消 | 统一密码 |
| 体育场馆 | 场景、场地、逐日可约、我的预约（只读） | 统一密码 |
| 任务与门户 | 办事大厅目录、我的待办/进行中/抄送、门户个人卡片（未读邮件/在借/待办计数） | 统一密码 |
| 学术科研 | 订阅数据库注册表、CARSI 校外 SSO（`scholar ensure` 建立会话）、DOI→PDF 全文下载、科研进展、导师名录、HPC 集群、报销与经费制度 | 部分免账号 |
| 就业 | 招聘岗位、招聘会、宣讲会：最新＋深列表＋详情 | 免账号 |
| 培养方案 | 专业学分要求与课程表、课程体系、通识课目录、课程搜索 | 免账号 |
| 校园生活 | 校历周次与假期、班车时刻与 ICS、每日信息快照（`context`/`digest`）、食堂咖啡、公寓、校区地图与 720° 全景、打印网点 | 免账号 |
| 讲义下载 | OneDrive/SharePoint 分享讲义免账号直读与下载（需 `[browser]` 可选增强） | 免账号 |
| 信息检索 | 官网全站搜索、新闻、讲座活动、学院动态、学生百科 WikiLake | 免账号 |
| 系统盘点 | 90+ 项服务注册表、子站在线普查、站点栏目、服务可达性、VPN 状态与隧道路由 | 免账号 |
| 图书馆 | 新版阿法迪云平台书目检索（`lib search`）、在借图书与应还查询（`lib loans`）、在借图书在线续借（`lib renew`，受控写操作） | 部分免账号 |
| 自助文印 | 联创云打印网点列表、待打印作业、文件上传云打印（`pms print`）与作业取消（`pms cancel`，受控写操作） | 部分免账号 |

体育场馆与图书馆座位属于独立系统，与预约中心的对照见 [docs/module_audit.md](docs/module_audit.md)；办事门户 `affairs portal` 接口近期因服务端变更暂不可用。个人档案类（学籍/住宿/荣誉/志愿/资助/社团）相关只读命令可通过 `westlake find` 检索。

## 快速开始

**图形化快速启动**：运行仓库根目录的 `start.bat`（Windows）、`start.command`（macOS）或 `./start.sh`（Linux）。首次运行时会自动安装依赖并启动浏览器；若未配置账号会自动进入「设置」页，由用户录入学号与统一身份认证密码，验证通过后进入仪表盘。若端口已有服务运行，会自动复用已有实例。

**终端**（已发布 PyPI，无需 clone 仓库）：

```bash
pip install westlake-survival   # PyPI 直装；开发装法：clone 后 pip install -e .，锁验证过的版本用 requirements.txt
westlake                      # 启动 Web 服务并打开浏览器；自动化环境可设 WESTLAKE_NO_WEBUI=1 禁用浏览器唤起
westlake calendar today       # 校历等公开功能无需账号
westlake --help
```

启动行为与首次配置的完整契约见 [docs/first_run.md](docs/first_run.md)。若遇到依赖缺失或运行异常，可先执行 `westlake doctor` 检查 Python 解释器、依赖包、账号配置与网络状态，根据提示完成修复（详见 [docs/doctor.md](docs/doctor.md)）。

## 配合 AI 代理使用（任何代理通用）

本项目针对自动化流程与 AI Agent 进行了专门设计，支持以下接入方式：

1. **基于 `AGENTS.md` 规范的 Agent**（ZCode、DSH、Codex、Claude Code、Cursor 等）：根目录 [AGENTS.md](AGENTS.md) 约定了行为规范、调用入口与验证流程；完成账号配置后直接调用 `westlake` CLI。
2. **Skill 机制接入**：技能定义文件位于 [skills/westlake-survival/SKILL.md](skills/westlake-survival/SKILL.md)，将其复制至对应 Agent 框架的技能目录即可加载：
   ```bash
   git clone https://github.com/yizhang-dream/westlake_survival.git
   cp -r westlake_survival/skills/westlake-survival ~/.zcode/skills/    # ZCode；其他代理用 ~/.agents/skills/、~/.claude/skills/ 等
   ```
3. **MCP 客户端接入**：安装包后配置并启动 `westlake-mcp` 服务端；配置示例与 MCP 工具清单见 [docs/skill_reference.md](docs/skill_reference.md)。

Agent 接入后建议优先运行 **`westlake doctor`**（支持 `--json` 输出）：各项检查通过后再开展后续工作；账号信息须引导使用者在本地网页「设置」页面自行填写，Agent 勿代填。

## 凭据与隐私

- **统一身份认证**：SIS、Canvas、AMS、场地预约、体育系统、自助打印与校内门户均接入统一身份认证；Canvas 额外支持配置个人访问令牌。
- **单一存储与本地保护**：优先采用系统钥匙串（Windows 凭据管理器 / macOS Keychain / Linux Secret Service）；写入本地文件时自动清理钥匙串对应项，反之亦然（[docs/credential_single_store.md](docs/credential_single_store.md)），不跨设备同步。
- **凭据录入隔离**：终端默认不提示输入明文密码（无桌面环境可通过 `westlake setup --terminal` 配置）；自动化与隔离测试可设置 `WESTLAKE_HOME` 或 `WESTLAKE_NO_KEYRING` 进入沙箱模式。
- **网络默认直连**：网络会话默认设置 `trust_env=False`，忽略 `HTTP_PROXY/HTTPS_PROXY` 代理设置，避免校园内网服务因代理转发出现异常；外部脚本可通过 `westlake_survival.discovery.direct_session()` 建立直连会话。
- 校外访问教务/Canvas 需校园网或 VPN：`westlake vpn status` 查状态。

## 验证（端到端）

本仓库不维护单元测试，功能验证一律端到端真跑：

```bash
python tools/module_smoke.py   # 精选集（匿名+离线，不依赖账号）逐条真跑并输出状态表
python tools/module_smoke.py --auth   # 需凭据的 68 条：用本机已配置的账号真跑
python tools/webui_smoke.py    # 进程内启动真实 Flask 服务并验证各页面响应（不依赖凭据）
python tools/pii_scan.py       # 提交前扫描敏感个人信息
```

`--auth` 组不绑任何具体账号的内容：课程、作业、讨论主题、会话、可约资源、
已登记分享等参数在运行时**自举**（先列该账号真实内容、取第一项替换占位符），
日期动态生成；该账号没有此类内容时标 `SKIP`，任何人的账号都能跑出有效结果。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/first_run.md](docs/first_run.md) | 启动行为与首次配置契约 |
| [docs/doctor.md](docs/doctor.md) | 环境自检逐项说明 |
| [docs/version_design.md](docs/version_design.md) | 语义化版本体系与更新契约设计（参考 archify 设计） |
| [docs/skill_reference.md](docs/skill_reference.md) | 命令示例、Python API 方法表、MCP 注册 |
| [docs/credential_single_store.md](docs/credential_single_store.md) | 「凭据只存一份」的设计与实现 |
| [docs/ams.md](docs/ams.md) / [docs/sports.md](docs/sports.md) / [docs/wikilake.md](docs/wikilake.md) / [docs/clubwiki.md](docs/clubwiki.md) / [docs/hidden_services.md](docs/hidden_services.md) | 各系统深挖注记 |
| [docs/library.md](docs/library.md) | 图书馆新旧系统与阿法迪云接入 |
| [docs/write_actions.md](docs/write_actions.md) | 受控写操作白名单（14 项）与 Action Card 安全门设计 |
| [docs/module_audit.md](docs/module_audit.md) | 各系统边界与归因审计 |
| [docs/performance.md](docs/performance.md) / [docs/portability.md](docs/portability.md) | 性能架构与跨平台规范 |

## 许可与致谢

- 许可：[PolyForm Noncommercial 1.0.0](LICENSE)，仅限非商业用途并保留署名。
- 致谢：结构参考 [sustech_survival](https://github.com/dumixthestpd/sustech_survival)；社团简介改写自学生自建百科 WikiLake 并逐条附原文链接（[docs/clubwiki.md](docs/clubwiki.md)）。
- 本项目为社区工具，无西湖大学官方背书；仅访问使用者本人有权的数据。
