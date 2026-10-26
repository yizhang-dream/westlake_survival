"""全校 68 域名中「未接内容页」站点的统一内容读取层。

2026-10-25 批量探测（直连 + 编码兜底）后按形态分类接入；2026-10-24 深挖批
加入两层能力：

- **博达栏目发现器**（:func:`_discover_baida_columns`）：抓首页导航锚点
  -> 逐个 GET 候选栏目页 -> ``info/`` 条目 ≥2 才收录。手工 ``cols`` 只做
  种子，其余栏目（奖学金 / 勤工助学 / 招标公告等同构栏）全自动补全，
  单站上限 12 栏。
- **HPC 中心**（:data:`HPC_SITES`）：Vue SPA 壳，内容在公网 mkdocs/sphinx
  手册（四套目录树）+ 校内网成果库 PHP API（直连 -> 系统代理双通道，
  不通时优雅降级）+ 资料 PDF。

典型坑：博达响应无 charset 头须 :func:`_decoded` 重解码；Jinja 里数据
键名避开 ``items``（dict 方法）；sphinx rtd 主题 ``class`` 与 ``href``
先后顺序不定。

特例站（SPA / 登录墙 / 三维演示）不做内容抓取，保留入口与简介（见
:data:`INTRO_SITES`）。全部只读 ``GET``；不碰登录与写操作。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

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
    "brcfen": {"name": "生物医学实验技术中心（EN）", "group": "科研平台",
               "cols": {"通知公告": "index/tzgg.htm", "新闻资讯": "index/xwzx.htm",
                        "亮点服务": "index/ldfw.htm"}},
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
HOMEPAGE_SITES: dict = {}

#: TRS 组件列表栏（2026-10-25 逐站反出）：导航树藏在 ``header.navList``
#: 组件 JSON 里（非裸 HTML 锚点，猜路径全 404/500），真栏目路径如下。
#: cols: 标签 -> {path, comp, key, title 字段, date 字段}；banner=True 先抓首页 Banner。
TRS_LIST_SITES: dict = {
    "graduateschool": {
        "name": "研究生院", "group": "招生与基金", "banner": True,
        "cols": {"通知公告": {"path": "Notice/", "comp": "notice",
                              "key": "rightList", "title": "text"},
                 # 三棵树都是 JS 跳转壳 -> ./Supervisors/，组件 list=8 个子标签页，
                 # 每个子页 rightList=条目（tabs 模式逐子页抓）。
                 "规章制度": {"path": "Regulations/Supervisors/", "comp": "regulations",
                              "key": "rightList", "title": "text", "tabs": True},
                 "办事指南": {"path": "Guidelines/Supervisors/", "comp": "regulations",
                              "key": "rightList", "title": "text", "tabs": True},
                 "下载专区": {"path": "Download/Supervisors/", "comp": "regulations",
                              "key": "rightList", "title": "text", "tabs": True}},
    },
    "wudf": {
        "name": "发展基金会（捐赠）", "group": "招生与基金",
        "cols": {
            "捐赠新闻": {"path": "News_Center/Foundation_News/", "comp": "donationNews", "key": "list"},
            "机构公告": {"path": "News_Center/Institutional_Announcements/", "comp": "institutionNotice", "key": "list"},
            # 信息公示 = 分组 PDF（list[].reportsList[]{name,fileUrl}，相对链接）
            "信息公示": {"path": "Information_Disclosure/", "comp": "information",
                        "key": "list", "disclosure": True},
        },
    },
    "zh-ugadmissions": {
        "name": "本科招生网（中文）", "group": "招生与基金",
        "cols": {"招生动态": {"path": "Admissions/AdmissionEvents/",
                              "comp": "AdmissionEventsNew", "key": "list",
                              "date": "data"}},  # 官网把日期字段拼成了 data
    },
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
    # 英文镜像子站（2026-10-25 补）：内容主体已在双语模块/中文站，此处给入口。
    "eniscps": {"name": "物质科学公共实验平台（EN）", "group": "科研平台",
                "intro": "iscps 英文镜像（自研模板，info 链接为仪器目录非新闻）。"},
    "en": {"name": "英文主站", "group": "其他",
           "intro": "en.westlake.edu.cn；新闻/活动等双语内容走 news/events 的英文模式。"},
    "lifesciences": {"name": "生命科学学院（EN）", "group": "其他",
                     "intro": "sls 英文镜像（homePage 变体，列表结构与中文站不同）。"},
    "en-soe": {"name": "工学院（EN）", "group": "其他",
               "intro": "engineering 英文镜像（空壳状态，官网现状）。"},
}

#: 页面分组顺序。
SITE_GROUPS = ("科研平台", "部门机构", "招生与基金", "课题组", "其他")

#: 组内站点排序（2026-10-25 用户裁定「容易用到的放前面」）：学生日常高频
#: 在前（学生事务/IT/招生/研院/HPC），办事与低频机构在后；未列出的按字典序垫底。
SITE_ORDER: dict[str, list[str]] = {
    "科研平台": ["hpc", "brcf", "iscps", "iscms", "larc", "nanolab", "bioinfo",
                 "cap", "share", "brcfen", "eniscps", "astro"],
    "部门机构": ["osa", "info", "ohr", "facilities", "assets", "construction",
                 "ore", "oala", "huxin", "dq", "international"],
    "招生与基金": ["zh-ugadmissions", "graduateschool", "wudf", "qiushi",
                   "westlakefellows"],
    "课题组": ["yanglab", "audio", "2dmater", "eer.lab"],
    "其他": ["en", "lifesciences", "en-soe", "lams", "heqdata"],
}

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
    """把条目相对 URL 拼成绝对地址（相对站点根，条目 href 已剥 ../ 前缀）。

    2026-10-25 修复：旧实现 rsplit("/westlake.edu.cn") 在子域主机上永不
    命中（域名前是 ``.`` 不是 ``/``），产出 ``//westlake.edu.cn/info/…``
    双斜杠坏链——列表页所有条目点开全 404，e2e 只断言了前缀没拦住。
    """
    if url.startswith("http"):
        return url
    return urljoin(base, url.lstrip("./"))


def _host(key: str) -> str:
    """站点 key -> 主机根 URL。"""
    return f"https://{key}.westlake.edu.cn/"


#: 首页锚点（href + 锚内 120 字符文本），用于栏目发现。
_HOMEPAGE_ANCHOR_RE = re.compile(r'<a[^>]+href="([^"#]+?\.htm)"[^>]*>([\s\S]{0,120}?)</a>')
#: 候选栏目路径：可选一级目录 + 文件名.htm（info/ 条目是两级数字目录，天然不匹配）。
_COL_PATH_RE = re.compile(r"^(?:\.\./)?(?:[A-Za-z0-9_]+/)?[A-Za-z0-9_]+\.htm$")
#: 非栏目标签（导航装饰 / 分页），命中即弃（比较前压掉全角/半角空白）。
_SKIP_LABELS = {"更多", "more", "MORE", "详情", "首页", "主页", "home", "HOME",
                "返回", "下一篇", "上一篇", "English", "登录", "检索"}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[\s\u3000]+")


def _clean_label(raw: str) -> str:
    """锚文本 -> 栏目标签：去标签、压空白。"""
    return _WS_RE.sub("", _TAG_RE.sub("", raw).replace("&nbsp;", " ")).strip()


def _norm_col_path(href: str) -> str:
    """栏目路径规范化：剥 ../ 前缀（首页常写 index/tzgg.htm 或 tzgg.htm 等价）。"""
    return href.lstrip("./").removeprefix("../")


def _discover_baida_columns(key: str, s, manual_paths: set[str],
                            limit: int, max_pages: int = 14) -> list[SiteSection]:
    """从首页导航链接逐个探测内容栏目（含 ≥2 条 info/ 条目才收录）。

    2026-10-24 深挖批：手工 cols 只覆盖每站 1-2 个栏目，导航里其实还有
    奖学金 / 勤工助学 / 招标公告等同构栏目；本发现器把「找到链接→
    一步步深挖」固化：首页锚点 -> 栏目页 -> info/ 条目计数验证。
    """
    base = _host(key)
    try:
        html = _decoded(s.get(base, timeout=DEFAULT_TIMEOUT))
    except Exception:
        return []
    candidates: list[tuple[str, str]] = []
    seen = set(manual_paths)
    for m in _HOMEPAGE_ANCHOR_RE.finditer(html):
        href, inner = m.group(1), m.group(2)
        if href.startswith(("http", "javascript", "mailto")):
            continue
        norm = _norm_col_path(href)
        if not _COL_PATH_RE.fullmatch(norm) or norm in seen:
            continue
        filename = norm.rsplit("/", 1)[-1]
        if filename.removeprefix("index").isdigit() and filename != "index.htm":
            continue  # 分页（list2.htm / tzgg2.htm）
        label = _clean_label(inner)
        if not (2 <= len(label) <= 20) or label in _SKIP_LABELS:
            continue
        seen.add(norm)
        candidates.append((norm, label))
        if len(candidates) >= max_pages:
            break
    sections: list[SiteSection] = []
    for norm, label in candidates:
        try:
            items = _column_items(s, base, norm, limit)
        except Exception:
            continue
        if len(items) >= 2:
            sections.append(SiteSection(label=label, items=items))
    return sections


def _column_items(s, base: str, path: str, limit: int) -> list:
    """取一个栏目的条目：第 1 页 + 第 2 页分页（博达 ``<拼音>/2.htm`` 规则）。

    深挖层 1.5：栏目首页只挂最新 ~10 条，第 2 页补历史条目；仅翻一页
    控制请求预算。404 / 无新条目即停。
    """
    resp = s.get(base + path, timeout=DEFAULT_TIMEOUT)
    items = _extract_items(_decoded(resp), base, limit)
    stem = path.rsplit("/", 1)[-1][:-4]
    parent = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
    seen = {i.url for i in items}
    if len(items) >= max(4, limit // 2):
        try:
            r2 = s.get(f"{base}{parent}{stem}/2.htm", timeout=DEFAULT_TIMEOUT)
            more = _extract_items(_decoded(r2), base, limit) if r2.status_code == 200 else []
        except Exception:
            more = []
        for i in more:
            if i.url not in seen and len(items) < limit * 2:
                seen.add(i.url)
                items.append(i)
    return items


def _fetch_baida_columns(key: str, cols: dict, limit: int) -> list[SiteSection]:
    """抓博达站栏目：手工 cols 打头 + 首页发现器补全，单站上限 12 栏。"""
    base = _host(key)
    s = _session()
    sections = []
    for label, path in cols.items():
        items = _column_items(s, base, path, limit)
        if items:
            sections.append(SiteSection(label=label, items=items))
    discovered = _discover_baida_columns(
        key, s, {_norm_col_path(p) for p in cols.values()}, limit)
    known = [s_.label for s_ in sections]
    for sec in discovered:
        if sec.label not in known:
            sections.append(sec)
    return sections[:12]


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
            sections.append(SiteSection(label="办事指南目录", items=items))
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


#: HPC 中心：Vue SPA 壳 + mkdocs 手册（公网可达）+ 成果库 PHP API（仅校内网）。
HPC_SITES: dict = {
    "hpc": {"name": "高性能计算中心", "group": "科研平台"},
}

#: HPC 手册四套（2026-10-24 从 SPA bundle 的 manuals 数组反出真实路径；
#: science/ai 是 mkdocs-material，cryo 是 sphinx rtd 主题，WRAP 是静态标题页）。
_HPC_MANUALS = (
    ("science", "科学工程计算集群手册", "mkdocs"),
    ("ai", "GPU 集群用户手册", "mkdocs"),
    ("cryo", "冷冻电镜集群使用指南", "sphinx"),
    ("wrap", "WRAP（RNA-Seq 平台）文档", "headings"),
)
_HPC_MANUAL_URL = {
    "science": "document/science/",
    "ai": "document/ai/index.html",
    "cryo": "document/cryo/index.html",
    "wrap": "docs/shiny/document.html",
}

#: mkdocs-material 导航条目（属性可能带引号也可能裸写）。
_MKDOCS_NAV_RE = re.compile(
    r'href="?([-\w/]+\.html)"?\s+class="?(?:md-nav__link[^">]*)"?[^>]*>\s*'
    r'(?:<span[^>]*>\s*)?([^<]{2,40}?)\s*<'
)
#: sphinx rtd 主题 toctree 条目（class 与 href 先后顺序不定）。
_SPHINX_NAV_RE = re.compile(
    r'<a[^>]*?(?:class="reference[^"]*"[^>]*href="?([-\w/]+\.html)"?'
    r'|href="?([-\w/]+\.html)"?[^>]*class="reference[^"]*")[^>]*>\s*([^<]{2,50}?)\s*<'
)
#: 静态文档页标题（h1/h2 章节列表）。
_HEADING_RE = re.compile(r'<h[12][^>]*>\s*(?:<a[^>]*>\s*</a>)?\s*([^<]{3,80}?)\s*<')

#: 成果库 API 的 type 代码 -> 栏目（SPA 里 partObj: article=1 patent=2 soft=3）。
_HPC_ESSAY_TYPES = {"1": "学术论文", "2": "专利", "3": "软件成果"}
_ESSAY_API = "http://172.16.75.35:8007/selectessay.php"
#: 双通道失败后的负缓存（30 分钟内不再试，避免每页白等 8s 超时）。
_essays_fail_until: float = 0.0


def _hpc_manual_sections(base: str, s, limit: int) -> list[SiteSection]:
    """抓四套手册的目录树（每章一节条目，无日期）。三种 markup 分别抽。"""
    sections = []
    for dir_name, label, kind in _HPC_MANUALS:
        path = _HPC_MANUAL_URL[dir_name]
        try:
            resp = s.get(base + path, timeout=DEFAULT_TIMEOUT)
            html = _decoded(resp)
        except Exception:
            continue
        root = base + path.rsplit("/", 1)[0] + "/"
        if kind == "mkdocs":
            pairs = _MKDOCS_NAV_RE.findall(html)
        elif kind == "sphinx":
            nav_start = html.find("wy-menu")
            nav_end = html.find("</nav>", nav_start)
            pairs = [(g1 or g2, t) for g1, g2, t in _SPHINX_NAV_RE.findall(
                html[nav_start:nav_end])] if nav_start != -1 else []
        else:  # 静态标题页：h1/h2 即章节，无锚点则用序号伪锚去重
            pairs = [(f"{path}#sec-{i}", t)
                     for i, t in enumerate(_HEADING_RE.findall(html))]
            root = base
        items, seen = [], set()
        for href, title in pairs:
            title = title.strip()
            if href in seen or not title or len(title) < 2:
                continue
            seen.add(href)
            items.append(SiteItem(title=title, url=urljoin(root, href)))
        if len(items) >= 3:
            sections.append(SiteSection(label=label, items=items[: max(limit * 2, 16)]))
    return sections


def _hpc_essay_sections(limit: int) -> list[SiteSection]:
    """成果库 API（论文/专利/软件）。仅校内网可达：先直连，再走系统代理。

    2026-10-24 实测：校外 / 代理节点不在校内路由时两端都 502/超时，
    此时返回空并在 error 里说明，不硬凑。
    """
    import requests as _rq
    import time as _time

    global _essays_fail_until
    if _time.monotonic() < _essays_fail_until:
        raise WestlakeError("成果库 API 仅校内网可达（近期已失败，负缓存中）")
    last_exc = None
    for use_proxy in (False, True):
        try:
            sess = _rq.Session()
            sess.trust_env = use_proxy
            resp = sess.get(_ESSAY_API, timeout=4)
            data = resp.json()
            if str(data.get("code")) != "200":
                last_exc = WestlakeError(f"code={data.get('code')}")
                continue
            by_type: dict[str, list] = {}
            for row in data.get("data") or []:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                if not title:
                    continue
                by_type.setdefault(str(row.get("type")), []).append(SiteItem(
                    title=title,
                    url=str(row.get("link") or ""),
                    date=str(row.get("datetime") or "")[:16],
                ))
            return [
                SiteSection(label=_HPC_ESSAY_TYPES[t], items=rows[:limit])
                for t in ("1", "2", "3") if (rows := by_type.get(t))
            ]
        except Exception as exc:  # noqa: BLE001 - 双通道各自的失败都要记录
            last_exc = exc
    _essays_fail_until = _time.monotonic() + 1800
    raise WestlakeError(f"成果库 API 仅校内网可达（{last_exc.__class__.__name__}）")


def _fetch_hpc(key: str, limit: int) -> tuple[list[SiteSection], str]:
    """HPC 站：手册导航 + 成果库 + 资料 PDF。返回 (sections, note)。"""
    base = _host(key)
    s = _session()
    sections = _hpc_manual_sections(base, s, limit)
    note = ""
    try:
        sections.extend(_hpc_essay_sections(limit))
    except WestlakeError as exc:
        note = str(exc)
    sections.append(SiteSection(label="资料下载", items=[
        SiteItem(title="HPC 用户手册（PDF）", url=f"{base}hpc_user.pdf"),
        SiteItem(title="HPC 服务介绍（PDF）", url=f"{base}hpc_service.pdf"),
    ]))
    return sections, note


# --------------------------------------------------------------------------- #
# 条目详情（深挖层 2：点进列表页的每一条）
# --------------------------------------------------------------------------- #
#: 详情页只允许校内域（防 SSRF；只读 GET）。
_DETAIL_HOST_RE = re.compile(r"^https?://[a-z0-9.\-]+\.westlake\.edu\.cn(?::\d+)?/", re.I)
#: 正文容器：博达 v_news_content / TRS_Editor / mkdocs article / sphinx body，四形态。
_CONTENT_BLOCK_RES = (
    re.compile(r'class="[^"]*v_news_content[^"]*"[^>]*>([\s\S]{40,6000}?)</div>', re.I),
    re.compile(r'id="[^"]*TRS_Editor[^"]*"[^>]*>([\s\S]{40,6000}?)</div>', re.I),
    re.compile(r'<article[^>]*class="[^"]*md-content[^"]*"[^>]*>([\s\S]{40,6000}?)</article>', re.I),
    re.compile(r'<div[^>]*class="[^"]*body[^"]*"[^>]*>([\s\S]{40,6000}?)</div>', re.I),
    re.compile(r'<div[^>]*class="[^"]*(?:content|article|detail)[^"]*"[^>]*>([\s\S]{40,6000}?)</div>', re.I),
)
#: 正文截断标记（博达详情页尾部的上下篇 / 相关阅读导航）。
_EXCERPT_CUT_RE = re.compile(r"(上一篇|下一篇|相关阅读|责任编辑|【打印】|版权所有)")
_ATTACHMENT_RE = re.compile(
    r'<a[^>]+href="([^"]+\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|wps))"[^>]*>([^<]{1,80})</a>', re.I)
_WS_COLLAPSE_RE = re.compile(r"\s+")
#: 详情 TTL 缓存（模块级，进程内 10 分钟）。
_detail_cache: dict[str, tuple[float, dict]] = {}
_DETAIL_TTL = 600.0


def _strip_html(fragment: str) -> str:
    """去标签去脚本样式，压空白。"""
    fragment = re.sub(r"<(script|style)[\s\S]*?</\1>", "", fragment, flags=re.I)
    return _WS_COLLAPSE_RE.sub("", _TAG_RE.sub("", fragment).replace("&nbsp;", " ")).strip()


#: 详情页里的表格（名单公示 / 课表 / 补贴表——正文之外的硬数据）。
_TABLE_BLOCK_RE = re.compile(r"<table[\s\S]{30,12000}?</table>", re.I)
_TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.I)
_TD_RE = re.compile(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", re.I)


def _extract_tables(html: str, limit: int = 3) -> list[list[list[str]]]:
    """抽详情页数据表：≥2 行且 ≥2 列才算（滤掉布局表格），每表至多 12 行。"""
    tables: list[list[list[str]]] = []
    for tm in _TABLE_BLOCK_RE.finditer(html):
        rows: list[list[str]] = []
        for rm in _TR_RE.finditer(tm.group(0)):
            cells = [_strip_html(c)[:48] for c in _TD_RE.findall(rm.group(1))]
            if any(cells):
                rows.append(cells[:10])
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            tables.append(rows[:12])
        if len(tables) >= limit:
            break
    return tables


def site_detail(url: str) -> dict:
    """抓一条站内页面的详情：标题 / 正文摘要 / 附件下载。

    深挖层 2：列表页只给「标题+日期」，本函数点进条目页把正文摘要和
    附件（申请表 PDF / DOC 等——学生真正要下载的东西）挖出来。
    仅允许 ``*.westlake.edu.cn``（只读 GET，防 SSRF）。
    """
    if not _DETAIL_HOST_RE.match(url):
        raise WestlakeError("仅支持 *.westlake.edu.cn 站内页面")
    import time as _time

    now = _time.monotonic()
    hit = _detail_cache.get(url)
    if hit and now - hit[0] < _DETAIL_TTL:
        return hit[1]
    s = _session()
    resp = s.get(url, timeout=DEFAULT_TIMEOUT)
    html = _decoded(resp)
    title_m = re.search(r"<title>([^<]+)</title>", html)
    title = (title_m.group(1).strip() if title_m else "").rsplit("-", 1)[0].strip()
    excerpt = ""
    for pat in _CONTENT_BLOCK_RES:
        m = pat.search(html)
        if not m:
            continue
        text = _strip_html(m.group(1))
        cut = _EXCERPT_CUT_RE.search(text)
        if cut:
            text = text[: cut.start()]
        if len(text) >= 30:
            excerpt = text[:280]
            break
    if not excerpt:  # 容器全失手时退化为整页文本
        body = re.search(r"<body[\s\S]*?</body>", html)
        text = _strip_html(body.group(0) if body else html)
        cut = _EXCERPT_CUT_RE.search(text)
        excerpt = (text[: cut.start()] if cut else text)[:280]
    attachments = []
    for href, name in _ATTACHMENT_RE.findall(html):
        name = name.strip() or href.rsplit("/", 1)[-1]
        attachments.append({"name": name[:60], "url": urljoin(url, href)})
    data = {"url": url, "title": title, "excerpt": excerpt,
            "attachments": attachments[:8], "tables": _extract_tables(html)}
    if len(_detail_cache) > 300:
        _detail_cache.clear()
    _detail_cache[url] = (now, data)
    return data


def _fetch_trs_list(key: str, config: dict, limit: int) -> list[SiteSection]:
    """TRS 组件列表栏：逐栏取页面 -> 组件块 -> ``array_of(key)`` -> 条目。"""
    from westlake_survival._trs import array_of, component_script

    base = _host(key)
    s = _session()
    sections: list[SiteSection] = []
    if config.get("banner"):
        try:
            sections.extend(_fetch_homepage_banner(key, limit))
        except Exception:  # noqa: BLE001 - Banner 失败不拖垮栏目
            pass
    for label, cfg in config["cols"].items():
        try:
            page_url = base + cfg["path"]
            html = _decoded(s.get(page_url, timeout=DEFAULT_TIMEOUT))
            block = component_script(html, cfg["comp"])
            rows = array_of(block, cfg["key"]) if block else []
        except Exception:  # noqa: BLE001 - 单栏失败继续
            continue
        items = []
        title_f, date_f = cfg.get("title", "title"), cfg.get("date", "date")

        def _push(row: dict) -> None:
            title = str(row.get(title_f) or row.get("name") or "").strip()
            if not title:
                return
            items.append(SiteItem(
                title=title[:90],
                url=str(row.get("url") or row.get("fileUrl") or base),
                date=str(row.get(date_f) or "")[:10]))

        if cfg.get("disclosure"):  # 分组 PDF：list[].reportsList[]{name,fileUrl}
            for group in rows:
                if not isinstance(group, dict):
                    continue
                for entry in group.get("reportsList") or []:
                    if isinstance(entry, dict):
                        entry["url"] = urljoin(page_url, str(entry.get("fileUrl") or ""))
                        _push(entry)
                        if len(items) >= limit:
                            break
        elif cfg.get("tabs"):  # 子标签树：list[]=子栏页，逐页抓 key 条目
            for row in rows:  # 根页（当前子栏）自己的条目先入
                if isinstance(row, dict):
                    _push(row)
            tabs = array_of(block, "list") or []
            sub_urls: list[str] = []
            for tab in tabs:
                if not isinstance(tab, dict):
                    continue
                sub = str(tab.get("url") or "")
                if sub and sub != page_url and sub not in sub_urls:
                    sub_urls.append(sub)
            for sub in sub_urls[:8]:
                try:
                    sub_html = _decoded(s.get(sub, timeout=DEFAULT_TIMEOUT))
                    sub_block = component_script(sub_html, cfg["comp"])
                    for row in array_of(sub_block, cfg["key"]) if sub_block else []:
                        if isinstance(row, dict):
                            _push(row)
                except Exception:  # noqa: BLE001 - 子页失败继续
                    continue
        else:
            for row in rows:
                if isinstance(row, dict):
                    _push(row)
                if len(items) >= limit:
                    break
        if items:
            sections.append(SiteSection(label=label, items=items[:limit]))
    return sections


def site_content(key: str, limit: int = 8) -> SiteContent:
    """取一个站点的内容（博达 / 静态 / homePage / HPC / 特例简介五路分发）。"""
    config = BAIDA_SITES.get(key)
    if config is not None:
        content = SiteContent(key=key, name=config["name"], group=config["group"], url=_host(key))
        try:
            content.sections = _fetch_baida_columns(key, config.get("cols") or {}, limit)
        except Exception as exc:
            content.error = f"{exc.__class__.__name__}: {exc}"[:120]
        if not content.sections and not content.error:
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
    if key in TRS_LIST_SITES:
        config = TRS_LIST_SITES[key]
        content = SiteContent(key=key, name=config["name"], group=config["group"], url=_host(key))
        try:
            content.sections = _fetch_trs_list(key, config, limit)
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
    if key in HPC_SITES:
        config = HPC_SITES[key]
        content = SiteContent(key=key, name=config["name"], group=config["group"], url=_host(key))
        try:
            content.sections, note = _fetch_hpc(key, limit)
            if note:
                content.intro = note
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
        elif key in TRS_LIST_SITES:
            cfg = TRS_LIST_SITES[key]
            has_cols = True
        elif key in STATIC_SITES:
            cfg = STATIC_SITES[key]
            has_cols = True
        elif key in HOMEPAGE_SITES:
            cfg = HOMEPAGE_SITES[key]
            has_cols = True
        elif key in HPC_SITES:
            cfg = HPC_SITES[key]
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
    """全部已接入站点 key（博达 + TRS 列表 + 静态 + homePage + HPC + 特例）。"""
    return sorted({*BAIDA_SITES, *TRS_LIST_SITES, *STATIC_SITES,
                   *HOMEPAGE_SITES, *HPC_SITES, *INTRO_SITES})


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
        elif key in TRS_LIST_SITES:
            cfg = TRS_LIST_SITES[key]
        elif key in STATIC_SITES:
            cfg = STATIC_SITES[key]
        elif key in HOMEPAGE_SITES:
            cfg = HOMEPAGE_SITES[key]
        elif key in HPC_SITES:
            cfg = HPC_SITES[key]
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
        # 抓取失败必须显式失败：以前只打 stderr 且 exit 0，上层无从察觉站点已挂。
        click.secho(f"抓取异常：{content.error}", fg="red", err=True)
        raise SystemExit(1)
    for section in content.sections:
        click.echo(f"\n[{section.label}]")
        if not section.items:
            click.echo("  暂无条目")
            continue
        for item in section.items:
            date = f" {item.date}" if item.date else ""
            click.echo(f"  {item.title}{date}\n    {item.url}")


@cli_group.command(name="detail")
@click.argument("url")
def sites_detail(url: str) -> None:
    """抓一条站内页面详情：标题 / 正文摘要 / 表格 / 附件下载。"""
    data = site_detail(url)
    click.echo(data["title"] or data["url"])
    if data["excerpt"]:
        click.echo(f"摘要：{data['excerpt']}")
    for ti, table in enumerate(data.get("tables") or [], 1):
        click.echo(f"表格{ti}（{len(table)} 行）：")
        for row in table:
            click.echo("  " + " | ".join(row))
    if data["attachments"]:
        click.echo("附件：")
        for att in data["attachments"]:
            click.echo(f"  {att['name']}\n    {att['url']}")
    else:
        click.echo("附件：（无）")
