"""全校 68 域名中「未接内容页」站点的统一内容读取层。

2026-10-25 批量探测（直连 + 编码兜底）后按形态分三类接入：

- **博达 CMS 家族**（``VsbFormFunc`` 特征）：栏目页 ``index/<拼音>.htm`` 或
  ``<目录>/<拼音>.htm``，条目 ``info/<栏>/<文>.htm`` + ``title=`` 属性 +
  ``YYYY-MM-DD`` 日期，分页 ``<拼音>/N.htm``。典型坑：响应无 charset 头，
  ``requests`` 按 latin-1 解码成乱码，须 :func:`_decoded` 兜底重解码。
- **官网同款 TRS**（``new homePage(...)``）：研究生院；主 Banner 结构与
  ``schools.py`` 工学院同款，复用 :mod:`westlake_survival._trs`。
- **静态列表站**：首页 ``<a>`` + 日期直接抽（nanolab / lams / dq）。

特例站（SPA / 登录墙 / 三维演示）不做内容抓取，保留入口与简介（见
:data:`INTRO_SITES`）。全部只读 ``GET``；不碰登录与写操作。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import click

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.exceptions import WestlakeError

__all__ = [
    "SiteItem",
    "SiteSection",
    "SiteContent",
    "BAIDA_SITES",
    "STATIC_SITES",
    "HOMEPAGE_SITES",
    "INTRO_SITES",
    "SITE_GROUPS",
    "site_content",
    "sites_index",
    "all_sites",
    "cli_group",
]


@dataclass
class SiteItem:
    """一条站内条目（新闻 / 通知 / 文档）。"""

    title: str = ""
    url: str = ""
    date: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"title": self.title, "url": self.url, "date": self.date}


@dataclass
class SiteSection:
    """站点的一个栏目（标签 + 条目列表）。"""

    label: str = ""
    items: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"label": self.label, "items": [i.to_dict() for i in self.items]}


@dataclass
class SiteContent:
    """一个站点的内容（简介 + 栏目列表）。"""

    key: str = ""
    name: str = ""
    group: str = ""
    url: str = ""
    intro: str = ""
    sections: list = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "key": self.key,
            "name": self.name,
            "group": self.group,
            "url": self.url,
            "intro": self.intro,
            "sections": [s.to_dict() for s in self.sections],
            "error": self.error,
        }


#: 博达 CMS 站点配置：key -> {name, group, cols: {栏目标签: 栏目页路径}}。
#: 栏目路径均为 2026-10-25 直连实测；group 用于页面分组展示。
BAIDA_SITES: dict = {
    "brcf": {"name": "生物医学实验技术中心", "group": "科研平台",
             "cols": {"通知公告": "index/tzgg.htm", "新闻资讯": "index/xwzx.htm"}},
    "iscms": {"name": "分子科学公共实验平台", "group": "科研平台",
              "cols": {"平台新闻": "xwzx/ptxw.htm", "前沿资讯": "xwzx/qyzx.htm"}},
    "iscps": {"name": "物质科学公共实验平台", "group": "科研平台",
              "cols": {"新闻资讯": "xwzx.htm", "通知公告": "tzgg.htm"}},
    "larc": {"name": "实验动物中心", "group": "科研平台",
             "cols": {"公告资讯": "ggzx/ggtz.htm", "中心动态": "ggzx/zxdt.htm"}},
    "cap": {"name": "人工光合作用与太阳能燃料中心", "group": "科研平台",
            "cols": {"新闻动态": "xwdt.htm"}},
    "bioinfo": {"name": "基因组学与生物信息学核心实验室", "group": "科研平台",
                "cols": {"News": "NEWS___EVENTS/News.htm", "Events": "NEWS___EVENTS/Events.htm"}},
    "facilities": {"name": "实验室与科研设施部", "group": "部门机构",
                   "cols": {"通知公告": "tzgg.htm"}},
    "assets": {"name": "采购办公室", "group": "部门机构",
               "cols": {"信息公告": "index/xxgg.htm"}},
    "construction": {"name": "基本建设部", "group": "部门机构",
                     "cols": {"招标信息": "zbxx.htm"}},
    "huxin": {"name": "湖心讲堂", "group": "部门机构",
              "cols": {"动态汇总": "hxsy/dthz.htm", "新闻报道": "hxsy/xwbd.htm"}},
    "osa": {"name": "学生事务部", "group": "部门机构",
            "cols": {"通知公告": "xszz/tzgg.htm", "学生活动": "xszz/xshd.htm"}},
    "ohr": {"name": "人力资源部", "group": "部门机构",
            "cols": {"博士后通知": "bsh1/tzgg.htm", "政策文件": "zcwj1/zwzd.htm"}},
    "oala": {"name": "审计与法务办公室", "group": "部门机构",
             "cols": {"通知公告": "tzgg.htm"}},
    "iscms_intro": None,  # 占位删除
    "info": {"name": "信息技术中心（IT 服务台）", "group": "部门机构",
             "cols": {"规章制度": "gzzd.htm"}},
    "ore": {"name": "科技合作部", "group": "部门机构",
            "cols": {}},  # 办事型站点，无新闻栏；见 INTRO 兜底
}
BAIDA_SITES.pop("iscms_intro", None)

#: 静态列表站：首页直接抽 <a> + 日期。
STATIC_SITES: dict = {
    "nanolab": {"name": "先进微纳加工与测试平台", "group": "科研平台"},
    "lams": {"name": "站群地图", "group": "其他"},
    "dq": {"name": "党群工作部", "group": "部门机构"},
}

#: 官网同款 TRS（homePage 组件）：主 Banner 条目。
HOMEPAGE_SITES: dict = {
    "graduateschool": {"name": "研究生院", "group": "招生与基金"},
}

#: 不做内容抓取的特例站：SPA / 登录墙 / 三维演示 / 纯课题组页。
#: 页面仍展示入口与一句话简介（信息密度取舍的边界记录）。
INTRO_SITES: dict = {
    "2dmater": {"name": "二维材料与量子输运实验室", "group": "课题组",
                "intro": "课题组站（动画渲染为主），研究方向见官网。"},
    "audio": {"name": "李晓飞实验室", "group": "课题组",
              "intro": "量子声学课题组站，成员与论文见官网。"},
    "yanglab": {"name": "Yang Lab", "group": "课题组",
                "intro": "英文课题组站（News/People/Publications），见官网。"},
    "eer.lab": {"name": "生态环境研究实验室", "group": "课题组",
                "intro": "课题组站（前端渲染），动态见官网。"},
    "westlakefellows": {"name": "Westlake Fellows 项目", "group": "招生与基金",
                        "intro": "Fellows 项目介绍与申请（landing 页）。"},
    "international": {"name": "国际处", "group": "部门机构",
                      "intro": "国际交流项目与外籍服务（自研样式站）。"},
    "share": {"name": "大型仪器共享管理系统", "group": "科研平台",
              "intro": "仪器检索与预约需登录系统。"},
    "heqdata": {"name": "数据平台", "group": "其他",
                "intro": "科研数据管理平台，需登录。"},
    "astro": {"name": "天文平台", "group": "科研平台",
              "intro": "天文观测平台（Next.js SPA），内容见官网。"},
    "qiushi": {"name": "求是西湖", "group": "招生与基金",
               "intro": "求是西湖项目（活动信息 / 求是学者），静态站。"},
    "wudf": {"name": "发展基金会（捐赠）", "group": "招生与基金",
             "intro": "捐赠项目与校友基金（官网同款 TRS，首页无列表数据）。"},
}

#: 页面分组顺序。
SITE_GROUPS = ("科研平台", "部门机构", "招生与基金", "课题组", "其他")

_ITEM_LINK_RE = re.compile(
    r'href="(?:\.\./)*(?:(?:https?://)[^"]*?)?(info/[\w/]+\.htm)"[^>]*?>'
)
_ITEM_TITLE_RE = re.compile(r'title="([^"]+)"')
_ITEM_EM_RE = re.compile(r"<em>([^<]{4,90})</em>")
_ITEM_TEXT_RE = re.compile(r">\s*([^<>\s][^<]{4,80})<")
_SPAN_TAIL_RE = re.compile(r"</span>(\s*[^<\s][^<]{4,200})<")
_DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")


def _extract_items(html: str, base: str, limit: int) -> list:
    """从博达列表页抽条目：title= / <em> / 裸文本三形态 + 独立日期窗口。

    各站模板不一：多数 <a href title="标题">…<time>日期，assets/construction
    是 <a href><span>日期</span>标题（日期前置），larc 系是 <a href>文本。
    候选按 title、em、裸文本逐个试，跳过日期串（assets 的第一个文本节点恰是日期）。
    """
    items: list[SiteItem] = []
    for m in _ITEM_LINK_RE.finditer(html):
        href = m.group(1)
        window = html[m.end(): m.end() + 300]
        candidates: list[str] = []
        tm = _ITEM_TITLE_RE.search(html[max(0, m.start() - 10): m.end()])
        if tm:
            candidates.append(tm.group(1))
        candidates.extend(e.group(1) for e in _ITEM_EM_RE.finditer(window))
        candidates.extend(sp.group(1) for sp in _SPAN_TAIL_RE.finditer(window))
        candidates.extend(t.group(1) for t in _ITEM_TEXT_RE.finditer(window))
        title = ""
        for cand in candidates:
            cand = cand.strip()
            if cand and not _DATE_RE.fullmatch(cand) and not cand.startswith("20"):
                title = cand
                break
        if not title:
            continue
        dm = _DATE_RE.search(window) or _DATE_RE.search(
            html[max(0, m.start() - 40): m.end()]
        )
        items.append(
            SiteItem(title=title, url=_abs(base, href), date=dm.group(1) if dm else "")
        )
        if len(items) >= limit:
            break
    return items


def _session():
    """直连会话（绕系统代理，校园 DNS 通配 502 不算活）。"""
    from westlake_survival.discovery import direct_session

    return direct_session()


def _decoded(response) -> str:
    """博达站响应无 charset 头：requests 按 latin-1 解码出乱码，重解码兜底。"""
    text = response.text or ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _abs(base: str, url: str) -> str:
    """把条目相对 URL 拼成绝对地址。"""
    if url.startswith("http"):
        return url
    root = base.rsplit("/westlake.edu.cn", 1)[0] + "/westlake.edu.cn"
    return f"{root}/{url.lstrip('./')}"


def _host(key: str) -> str:
    """站点 key -> 主机根 URL。"""
    return f"https://{key}.westlake.edu.cn/"


def _fetch_baida_columns(key: str, cols: dict, limit: int) -> list[SiteSection]:
    """抓博达站各栏目列表页，返回栏目节。"""
    base = _host(key)
    s = _session()
    sections = []
    for label, path in cols.items():
        url = base + path
        resp = s.get(url, timeout=DEFAULT_TIMEOUT)
        html = _decoded(resp)
        sections.append(SiteSection(label=label, items=_extract_items(html, base, limit)))
    return sections


def _fetch_static_index(key: str, limit: int) -> list[SiteSection]:
    """静态站：首页抽含日期锚文本的条目。"""
    base = _host(key)
    s = _session()
    html = _decoded(s.get(base, timeout=DEFAULT_TIMEOUT))
    pattern = re.compile(
        r'<a[^>]+href="([^"]+\.htm)"[^>]*>\s*([^<]{6,70}?)\s*</a>'
        r"(?:(?!</a>).){0,120}?(20\d\d-\d\d-\d\d)?",
        re.S,
    )
    items = []
    for m in pattern.finditer(html):
        href, title, date = m.group(1), m.group(2).strip(), m.group(3)
        if not title or href.startswith(("css", "js")) or title in ("首页", "HOME"):
            continue
        items.append(SiteItem(title=title, url=_abs(base, href), date=date or ""))
        if len(items) >= limit * 2:
            break
    return [SiteSection(label="首页条目", items=items[:limit])]


def _fetch_homepage_banner(key: str, limit: int) -> list[SiteSection]:
    """官网同款 TRS：``new homePage(...)`` 的答辩公告 / 办事指南 / 主 Banner。

    研究生院实测键：``defenseAnnouncement.infoList``（学生姓名 / 论文题目 /
    地点 / 时间 / 详情链接）、``workGuide.infoList``（办事指南目录）。
    """
    from westlake_survival._trs import component_script, object_of
    from westlake_survival.exceptions import WestlakeError

    base = _host(key)
    s = _session()
    html = _decoded(s.get(base, timeout=DEFAULT_TIMEOUT))
    block = component_script(html, "homePage") or component_script(html, "homepage")
    sections: list[SiteSection] = []
    if not block:
        return sections
    try:
        defense = object_of(block, "defenseAnnouncement")
        rows = defense.get("infoList") or [] if isinstance(defense, dict) else []
        items = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("studentName") or "") + " " + str(row.get("topic") or "")[:40]
            if not title.strip():
                continue
            items.append(SiteItem(
                title=title.strip(), url=str(row.get("url") or base),
                date=str(row.get("data") or "")[:16]))
        if items:
            sections.append(SiteSection(label="答辩公告", items=items))
    except (WestlakeError, KeyError):
        pass
    try:
        guide = object_of(block, "workGuide")
        rows = guide.get("infoList") or [] if isinstance(guide, dict) else []
        items = [SiteItem(title=str(r.get("title") or ""),
                          url=str(r.get("href") or base))
                 for r in rows[:limit] if isinstance(r, dict) and r.get("title")]
        if items:
            sections.append(SiteSection(label="办事指南", items=items))
    except (WestlakeError, KeyError):
        pass
    try:
        banner = object_of(block, "mainBanner")
        rows = banner if isinstance(banner, list) else [banner]
        items = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("text") or "").strip()
            if not title:
                continue
            link = str(row.get("linkUrl") or row.get("url") or "")
            items.append(SiteItem(title=title, url=link or base, date=str(row.get("date") or "")))
        if items:
            sections.append(SiteSection(label="首页动态", items=items))
    except (WestlakeError, KeyError):
        pass
    return sections


def site_content(key: str, limit: int = 8) -> SiteContent:
    """取一个站点的内容（博达 / 静态 / homePage / 特例简介四路分发）。"""
    config = BAIDA_SITES.get(key)
    if config is not None:
        content = SiteContent(key=key, name=config["name"], group=config["group"], url=_host(key))
        if config.get("cols"):
            try:
                content.sections = _fetch_baida_columns(key, config["cols"], limit)
            except Exception as exc:
                content.error = f"{exc.__class__.__name__}: {exc}"[:120]
        if not content.sections:
            content.intro = "办事型站点，栏目为流程文档；入口直达。"
        return content
    if key in STATIC_SITES:
        config = STATIC_SITES[key]
        content = SiteContent(key=key, name=config["name"], group=config["group"], url=_host(key))
        try:
            content.sections = _fetch_static_index(key, limit)
        except Exception as exc:
            content.error = f"{exc.__class__.__name__}: {exc}"[:120]
        return content
    if key in HOMEPAGE_SITES:
        config = HOMEPAGE_SITES[key]
        content = SiteContent(key=key, name=config["name"], group=config["group"], url=_host(key))
        try:
            content.sections = _fetch_homepage_banner(key, limit)
        except Exception as exc:
            content.error = f"{exc.__class__.__name__}: {exc}"[:120]
        return content
    if key in INTRO_SITES:
        config = INTRO_SITES[key]
        return SiteContent(key=key, name=config["name"], group=config["group"],
                           url=_host(key), intro=config["intro"])
    raise KeyError(f"未知站点 {key!r}；可用：{', '.join(sorted(all_keys()))}")


def sites_index() -> list[dict]:
    """站点索引（不抓网络）：key / 名称 / 分组 / URL / 是否有栏目数据。"""
    rows: list[dict] = []
    for key in all_keys():
        if key in BAIDA_SITES:
            cfg = BAIDA_SITES[key]
            has_cols = bool(cfg.get("cols"))
        elif key in STATIC_SITES:
            cfg = STATIC_SITES[key]
            has_cols = True
        elif key in HOMEPAGE_SITES:
            cfg = HOMEPAGE_SITES[key]
            has_cols = True
        else:
            cfg = INTRO_SITES[key]
            has_cols = False
        rows.append({
            "key": key, "name": cfg["name"], "group": cfg["group"],
            "url": _host(key), "has_content": has_cols,
        })
    rows.sort(key=lambda r: (SITE_GROUPS.index(r["group"]) if r["group"] in SITE_GROUPS else 99, r["key"]))
    return rows


def all_keys() -> list[str]:
    """全部已接入站点 key（博达 + 静态 + homePage + 特例）。"""
    return sorted({*BAIDA_SITES, *STATIC_SITES, *HOMEPAGE_SITES, *INTRO_SITES})


def all_sites(limit: int = 8) -> list[SiteContent]:
    """抓全部站点内容（按分组顺序）。"""
    by_group: dict[str, list[SiteContent]] = {g: [] for g in SITE_GROUPS}
    for key in all_keys():
        content = site_content(key, limit=limit)
        by_group.setdefault(content.group, []).append(content)
    result: list[SiteContent] = []
    for group in SITE_GROUPS:
        result.extend(by_group.get(group, []))
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_table(rows, headers) -> None:
    """打印对齐文本表格（委托 ``cli.main._print_table``）。"""
    from westlake_survival.cli.main import _print_table as _impl

    _impl(rows, headers)


@click.group(name="sites", help="全校站点内容：博达 CMS / 静态 / TRS 三类统一读取。")
def cli_group() -> None:
    """``westlake sites`` 命令组（注册由 ``cli.main`` 完成）。"""


@cli_group.command(name="list")
def sites_list() -> None:
    """列出全部已接入站点与分组。"""
    rows = []
    for key in all_keys():
        if key in BAIDA_SITES:
            cfg = BAIDA_SITES[key]
        elif key in STATIC_SITES:
            cfg = STATIC_SITES[key]
        elif key in HOMEPAGE_SITES:
            cfg = HOMEPAGE_SITES[key]
        else:
            cfg = INTRO_SITES[key]
        rows.append((key, cfg["name"], cfg["group"]))
    _print_table(rows, ("key", "名称", "分组"))


@cli_group.command(name="site")
@click.argument("key")
@click.option("--limit", default=8, show_default=True, help="每栏目条数上限。")
def sites_site(key: str, limit: int) -> None:
    """显示一个站点的栏目与条目。"""
    content = site_content(key, limit=limit)
    click.echo(f"{content.name}（{content.group}） {content.url}")
    if content.intro:
        click.echo(content.intro)
    if content.error:
        click.secho(f"抓取异常：{content.error}", fg="red", err=True)
    for section in content.sections:
        click.echo(f"\n[{section.label}]")
        if not section.items:
            click.echo("  暂无条目")
            continue
        for item in section.items:
            date = f" {item.date}" if item.date else ""
            click.echo(f"  {item.title}{date}\n    {item.url}")
