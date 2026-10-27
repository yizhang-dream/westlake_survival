# WikiLake 只读检索（`westlake wiki`）

学生自建校园百科 <https://wiki.mestlake.cc> 的内容检索层。站点本身是 Docusaurus
静态站，**没有站内搜索**；这里用 sitemap + 按需抓正文补上目录、检索与单页正文。

与 [clubwiki.md](clubwiki.md) 的分工：clubwiki 是随包内置的 40 条**社团简介**（离线、
`/sis` 用）；本模块按需读**整站任意条目**（联网、有缓存、不落仓库内容）。

## 三个出口

| 出口 | 用法 |
|---|---|
| CLI | `westlake wiki list [--cat clubs]` / `westlake wiki search 班车 [--deep]` / `westlake wiki page 音游社` |
| MCP | `wiki_search`（query / deep / limit）、`wiki_page`（name） |
| WebUI | `/wiki`（搜索框 + 深浅检索开关 + 分类 chips），导航「百科」 |

`page` 的名称解析：条目名（`音游社`）、路径（`clubs/音游社`）、完整 URL 都接受；
名字走标题精确匹配，再退化为唯一的子串匹配。

## 数据与缓存

- 目录：`/sitemap.xml` → 142 条（2026-10-27，已剔除 `/tags/*` 与 `/markdown-page`），
  缓存 12 小时；网络失败时用任意旧缓存兜底。
- 正文：抓页后取 `<div class="theme-doc-markdown">`（实测正文容器是 div，不是
  `<article>`），深度计数切块，去脚本/样式/面包屑/「本页总览」等框架文案；
  表格单元格用 ` | ` 分隔。
- `--deep`：首次把全部页面抓一遍（并发 6、独立会话），正文索引缓存 12 小时；
  抓到一半以上才写缓存，避免半残结果长期驻留。实测冷启动约 10–20 秒。
- 全部是匿名公开请求，不带凭据；也不向站点提交任何内容。

## 边界与口径

- **只读**：不投递、不编辑、不评论。站内没有 API，抓的是渲染后的 HTML。
- **版权**：该站未声明许可证，内容版权归 WikiLake 贡献者。仓库里只落地了
  clubwiki 的改写简介；`westlake wiki` 的输出只在本地展示，不写入仓库。
- **PII**：`people` 栏目含真实姓名与照片，检索结果照原样展示但引用时自行判断，
  与本项目「不写真实学号/姓名」的口径（AGENTS.md）区分开。
- **稳定性**：站点结构变化会让正文提取退化为「抓不到正文」并明确报错，不会静默返回空。

## 验证（端到端）

```bash
westlake wiki list --cat guides        # 目录：应看到 交通/地图/日历/班车
westlake wiki search 班车               # 标题检索
westlake wiki search 铜鉴湖 --deep      # 正文检索（首次慢）
westlake wiki page guides/班车          # 单页正文
python tools/webui_smoke.py            # 含 /wiki 在内的全部页面 200
```
