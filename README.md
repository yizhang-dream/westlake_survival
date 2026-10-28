# westlake_survival

社区校园服务工具，Python 包、CLI 和 MCP 入口由 [pyproject.toml](pyproject.toml)定义，源码在 src/westlake_survival。

## 快速开始

不想开终端：双击仓库根目录的 `start.bat`（Windows）或 `start.command`（macOS）。首次运行自动装依赖，随后浏览器打开**「设置」页**——在那里填一次自己的学号与统一身份认证密码，课表/成绩/作业就通了。每台电脑各存各的，密码只留本机。

终端里等价的做法（启动的第一件事就是打开这个网页）：

```bash
pip install -e '.[webui]'   # 开发/跑测试再装 '.[test]'
westlake                    # 起网页并打开浏览器；首次直达「设置」，之后直达仪表盘
westlake --help
westlake calendar today     # 公开功能无需账号
```

脚本或自动化里不想被浏览器打断，用 `westlake --help` 或设 `WESTLAKE_NO_WEBUI=1`。启动行为与首次配置的完整契约见 [docs/first_run.md](docs/first_run.md)。

[使用技能](.zcode/skills/westlake-survival/SKILL.md)（ZCode 项目级技能，须放在 `.zcode/skills/` 才会被发现）与 examples/ 提供操作入口；[打印接口](src/westlake_survival/pms/api_notes.md)保留特定限制。Web 功能需 `[webui]` 额外依赖（上面快速开始已包含；`/capabilities` 一页列出 CLI+MCP+WebUI 全部能力，`/api/capabilities` 给 JSON），钥匙串需 `[secure]`。服务与数据范围：sso/sis 身份教务（课表/成绩/考试/评教/第二课堂成绩单/学业导师），canvas 课程与作业（含作业详情/题目附件/评分细则/课程文件下载/讨论区与公告/收件箱，以及提交作业、回帖、回私信三类写操作），lib/pms 借阅打印，booking 预约中心（17 类场地：自习室/研讨室/琴房/活动用房等，分类与资源、逐日可约状态、逐格空闲校验、我的预约，以及预约/取消两类写操作；体育场馆与图书馆座位是另外的系统，对照见 [docs/module_audit_2026-10-27.md](docs/module_audit_2026-10-27.md)），sport 体育场馆/游泳（独立正元系统 sportvenue，只读：场景/场地/逐日可约/我的预约），one/my 任务中心（待办/进行中/已处理/抄送/应用）与门户服务目录（`affairs portal` 2026-10-27 实测服务端接口疑似变化、暂报错），portal 门户个人卡片（未读邮件/在借图书/待办计数）与 AI 助手入口，scholar 学术资源（订阅数据库注册表、CARSI 联盟 SSO、校园 IP 信标、DOI→PDF 全文获取），program 本科培养方案（主站专业页：学分要求+课程表；通识课程目录；招生网：培养理念/课程体系），transit/calendar/ical/context 班车日历和快照，map 校区地图/全景/到校交通（全公开），share OneDrive/SharePoint 分享讲义（链接为「组织内任何人可查看」时免账号，需 `playwright` 与 `playwright install chromium`）。

SIS 与 Canvas 均可用统一身份认证密码（Canvas 也兼容令牌，网页「设置」可另存或清除令牌），需校园网/VPN；统一密码登录用 RSA 加密，`cryptography` 已列入基础依赖。授权与凭据见 [AGENTS](AGENTS.md)。凭据是本机状态（内存 / 环境变量 / 钥匙串 / 配置文件），不跨机器或系统用户同步。`westlake sso creds status` 只查来源。src/test 的 pytest 默认排除 live；在线状态以实际服务为准。端到端冒烟（不属 pytest）：`python tools/module_smoke.py [模块…] [--json out.json]` 把全部只读 CLI 命令真跑一遍出体检表（OK/EMPTY/AUTH/FAIL/MISSING），`python tools/webui_smoke.py [--verbose]` 进程内起真实 Flask 服务逐页 GET 断言 200（有失败则退出码 1）。

**网络与代理**：本包所有 HTTP 会话默认**直连**（无视 `HTTP_PROXY/HTTPS_PROXY`）。校园站点经系统代理常会 502/超时，所以直连是缺省；外部脚本复用请走 `westlake_survival.discovery.direct_session()` 或自建会话时设 `trust_env=False`。

社团简介补充数据见 [docs/clubwiki.md](docs/clubwiki.md)：40 条一句话介绍改写自学生自建百科 WikiLake（未声明许可，只存改写后的事实简介并逐条附原文链接，不含负责人信息与照片），随包内置、无凭据可读；`westlake aid orgs --wiki` 打印对照，`/sis` 有「社团简介」折叠块。要读 WikiLake 整站任意条目（该站没有站内搜索），用 `westlake wiki list/search/page`（MCP `wiki_search`/`wiki_page`、WebUI `/wiki`），设计见 [docs/wikilake.md](docs/wikilake.md)。

参考 sustech_survival，无学校官方背书。[PolyForm Noncommercial 1.0.0](LICENSE)仅限非商业用途并保留署名。
