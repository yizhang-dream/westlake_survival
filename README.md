# westlake_survival

社区校园服务工具，Python 包、CLI 和 MCP 入口由 [pyproject.toml](pyproject.toml)定义，源码在 src/westlake_survival。

```bash
pip install -e '.[test]'
westlake go               # 一步启动并自动开浏览器 →「设置」页填一次学号密码
westlake --help
westlake calendar today   # 公开功能无需账号
```

[使用技能](skills/westlake-survival/SKILL.md)与 examples/ 提供操作入口；[打印接口](src/westlake_survival/pms/api_notes.md)保留特定限制。Web 功能需 [webui]（`/capabilities` 一页列出 CLI+MCP+WebUI 全部能力，`/api/capabilities` 给 JSON），钥匙串需 [secure]。服务与数据范围：sso/sis 身份教务，canvas 课程与作业（含提交作业这一写操作），lib/pms 借阅打印，program 本科培养方案（主站专业页：学分要求+课程表；通识课程目录；招生网：培养理念/课程体系），transit/calendar/ical/context 班车日历和快照，map 校区地图/全景/到校交通 + 离线楼宇设施数据集。

SIS 需本人账号及校园网/VPN，Canvas 需本人令牌；授权与凭据见 [AGENTS](AGENTS.md)。`westlake sso creds status` 只查来源。src/test 的 pytest 默认排除 live；在线状态以实际服务为准。

参考 sustech_survival，无学校官方背书。[PolyForm Noncommercial 1.0.0](LICENSE)仅限非商业用途并保留署名。
