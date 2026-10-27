# 社团简介补充数据（WikiLake）

`/sis` 的「社团目录」只有名称与分类，看不出社团是做什么的。这里补一份随包内置的
一句话简介，数据来源是学生自建百科 **WikiLake**，不引入运行时网络依赖。

## 来源与许可

| 项 | 内容 |
|---|---|
| 站点 | <https://wiki.mestlake.cc/clubs/>（学生自建，非学校官方） |
| 仓库 | <https://github.com/MestlakeVniversity/wikilake>（无 LICENSE 文件） |
| 抓取日期 | 2026-10-27 |
| 存了什么 | 40 条**改写后**的事实性简介 + 原文链接（`src/westlake_survival/data/wikilake_clubs.json`） |
| 没存什么 | 负责人姓名、邮箱、照片、活动照片，以及站内的「梗」「人物」类内容 |

WikiLake 未声明许可证，内容版权归其贡献者。这里按最小引用处理：只留事实性的一句话
介绍，逐条附原文链接，供读者自行核对与溯源；若将来该站补充许可条款，以其为准。

需要检索**整站任意条目**（不只社团）时用 `westlake wiki`（联网、带缓存、不落仓库内容），
见 [wikilake.md](wikilake.md)。

## 用法

- WebUI：`/sis` 页「社团简介」折叠块（本地数据，无凭据也能读）；「社团目录」的
  每个社团名带 `title` 悬浮提示。
- CLI：`westlake aid orgs --wiki` 打印对照；不加 `--wiki` 时只提示命中数量。
- MCP：`sis_clubs`（我的社团）命中时附 `wiki_summary` / `wiki_url`。

## 匹配规则

`clubwiki.lookup()` 先归一化再比对：去空白与标点（含 `（）`「」等）、去「西湖大学」
前缀、去「社团/协会/俱乐部/社」后缀、`×` 视作 `x`。归一化后先精确匹配，长度 ≥3 时
再做包含匹配（用于「烘焙社（活力社团）」这类带评优后缀的名称）。

2026-10-27 实测：SIS 社团目录 39 条全部命中。

## 更新数据

站点条目会增加。更新时只做两件事：

1. 重新抓 `https://wiki.mestlake.cc/clubs/<社名>/`，按上面的口径改写简介；
2. 改 `src/westlake_survival/data/wikilake_clubs.json`，同步 `meta.fetched`。

改完跑 `python tools/webui_smoke.py` 与 `pytest src/test/capabilities/test_capabilities_e2e.py -q`
（后者真启服务并登录 SIS），确认 `/sis` 上「社团简介」块仍在、条目数对得上。
