# westlake_survival

社区校园服务工具，Python 包、CLI 和 MCP 入口由 [pyproject.toml](pyproject.toml)定义，源码在 src/westlake_survival。

```bash
pip install -e '.[test]'
westlake go               # 一步启动并自动开浏览器 →「设置」页填一次学号密码
westlake --help
westlake calendar today   # 公开功能无需账号
```

[使用技能](.zcode/skills/westlake-survival/SKILL.md)（ZCode 项目级技能，须放在 `.zcode/skills/` 才会被发现）与 examples/ 提供操作入口；[打印接口](src/westlake_survival/pms/api_notes.md)保留特定限制。Web 功能需 [webui]（`/capabilities` 一页列出 CLI+MCP+WebUI 全部能力，`/api/capabilities` 给 JSON），钥匙串需 [secure]。服务与数据范围：sso/sis 身份教务（课表/成绩/考试/评教/第二课堂成绩单/学业导师），canvas 课程与作业（含作业详情/题目附件/评分细则/课程文件下载/讨论区与公告/收件箱，以及提交作业、回帖、回私信三类写操作），lib/pms 借阅打印，booking 预约中心（场馆/教室/研讨室分类与资源、逐日可约状态、逐格空闲校验、我的预约，以及预约/取消两类写操作），one/my 任务中心（待办/进行中/已处理/抄送/应用）与门户服务目录，scholar 学术资源（订阅数据库注册表、CARSI 联盟 SSO、校园 IP 信标、DOI→PDF 全文获取），program 本科培养方案（主站专业页：学分要求+课程表；通识课程目录；招生网：培养理念/课程体系），transit/calendar/ical/context 班车日历和快照，map 校区地图/全景/到校交通（全公开）。

SIS 与 Canvas 均可用统一身份认证密码（Canvas 也兼容令牌，网页「设置」可另存或清除令牌），需校园网/VPN；统一密码登录用 RSA 加密，`cryptography` 已列入基础依赖。授权与凭据见 [AGENTS](AGENTS.md)。凭据是本机状态（内存 / 环境变量 / 钥匙串 / 配置文件），不跨机器或系统用户同步。`westlake sso creds status` 只查来源。src/test 的 pytest 默认排除 live；在线状态以实际服务为准。

**网络与代理**：本包所有 HTTP 会话默认**直连**（无视 `HTTP_PROXY/HTTPS_PROXY`）。校园站点经系统代理常会 502/超时，所以直连是缺省；外部脚本复用请走 `westlake_survival.discovery.direct_session()` 或自建会话时设 `trust_env=False`。

参考 sustech_survival，无学校官方背书。[PolyForm Noncommercial 1.0.0](LICENSE)仅限非商业用途并保留署名。
