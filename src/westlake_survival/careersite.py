"""西湖大学就业服务网（career.westlake.edu.cn）：公开三区块 + 登录态深列表。

背景（2026-10-24 实测；2026-10-27 接入登录态深列表）
======================================================
* 站点是就业信息系统：岗位 ``/campus/view/id/<n>``、招聘会 ``/jobfair/view/id/<n>``、
  宣讲会 ``/teachin/view/id/<n>`` 均为服务端渲染详情页。
* **首页三区块免登录**（招聘公告 / 招聘会 / 宣讲会），条目自带日期、时段、
  场地、状态（已举办等）与浏览数。
* 列表页（``/campus`` ``/jobfair`` ``/teachin`` ``/news``）匿名访问会重定向到
  iam 统一认证（2026-10-27 复测：``/campus`` 逐跳 302 终点落在
  ``iam.westlake.edu.cn/cas/login?service=…/default/westlake?role=student``）。
  登录态深列表与详情见 :func:`deep` / :func:`detail`，登录复用
  :func:`westlake_survival.iam.login_for` 直连会话（taskcenter 同款，无浏览器）。
  全站岗位检索入口 ``/job/search/…`` 同样需登录，尚未接入。
* **内嵌压缩块机制**（2026-10-27 匿名 news 列表/详情页实测）：列表与 news
  详情的内容不在 SSR 明文里，而是 ``Base64.decode(unzip("eJz…"))`` 内嵌——
  zlib 解压后形如 ``view2d<空格><base64>``，逐层 ``viewNd`` 标记 + base64，
  最内层是列表 HTML 或跳转 URL（news 详情是 320 字节跳转壳，解出
  mp.weixin.qq.com 外链）；campus/jobfair/teachin 详情页为 SSR 正文
  （2026-10-24 实测）。:func:`_unwrap_payloads` 统一解包。

数据只做读取与展示；条目链接指向官网详情页，投递等动作由本人完成。
"""

from __future__ import annotations

import base64
import logging
import re
import zlib
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import http_session
from westlake_survival.exceptions import AuthError, ParseError, WestlakeError

__all__ = [
    "CAREER_SITE_BASE",
    "CareerItem",
    "CareerDetail",
    "DEEP_KINDS",
    "announcements",
    "deep",
    "detail",
    "cli_group",
]

logger = logging.getLogger(__name__)

CAREER_SITE_BASE = "https://career.westlake.edu.cn"

_KIND_LABEL = {
    "campus": "招聘公告",
    "jobfair": "招聘会",
    "teachin": "宣讲会",
    "news": "新闻资讯",
}


@dataclass
class CareerItem:
    """就业服务网首页一条条目。"""

    kind: str  # campus | jobfair | teachin
    item_id: str = ""
    title: str = ""
    url: str = ""
    date: str = ""  # 2026.10.19 形态（日 + 月拼合）
    time: str = ""  # 13:30-16:00（仅活动类）
    venue: str = ""
    status: str = ""  # 已举办 / 未开始 / 报名中…
    views: str = ""

    @property
    def kind_label(self) -> str:
        return _KIND_LABEL.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "kind_label": self.kind_label,
            "id": self.item_id,
            "title": self.title,
            "url": self.url,
            "date": self.date,
            "time": self.time,
            "venue": self.venue,
            "status": self.status,
            "views": self.views,
        }


def _strip_tags(text: str) -> str:
    # 先反转义（站点正文里有 &lt;div&gt; 形态的转义标签与 &nbsp;），
    # 标签替换为空格避免相邻词粘连。
    import html as _html

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(text or ""))).strip()


def _parse_home(html: str) -> list[CareerItem]:
    """解析首页三区块（三种条目形态，2026-10-24 实测样例固化）。"""
    items: list[CareerItem] = []
    # 招聘公告：newsline 条目，line-time 两段 <p> + a.title
    for m in re.finditer(
        r'<span class="line-time"><p>(\d{1,2})</p>\s*<p>(20\d\d\.\d{1,2})</p></span>\s*'
        r'<a class="title"[^>]*title="([^"]*)"[^>]*href="/campus/view/id/(\d+)"',
        html,
    ):
        day, month, title, item_id = m.groups()
        items.append(CareerItem(
            kind="campus", item_id=item_id, title=title,
            url=f"{CAREER_SITE_BASE}/campus/view/id/{item_id}",
            date=f"{month}.{day}",
        ))
    # 招聘会 / 宣讲会：活动条目（line-time + view 链接 + 状态 + 时段 + 场地 + 浏览数）
    for m in re.finditer(
        r'<div class="line-time"><p>(\d{1,2})</p><p>(20\d\d\.\d{1,2})</p></div>(.*?)</li>',
        html,
        re.S,
    ):
        day, month, block = m.groups()
        link = re.search(r'href="/(jobfair|teachin)/view/id/(\d+)"', block)
        if not link:
            continue
        kind, item_id = link.group(1), link.group(2)
        title_html = re.search(r'class="title"[^>]*>(.*?)</a>', block, re.S)
        # 招聘会的状态 span 嵌在 <a> 内部，先摘掉再取纯标题
        title_raw = title_html.group(1) if title_html else ""
        title_raw = re.sub(r'<span[^>]*>(?:已举办|未开始|报名中|进行中)</span>', "", title_raw)
        title = _strip_tags(title_raw)
        status = ""
        sm = re.search(r'status-text[^>]*>([^<]+)<', block)
        if sm:
            status = sm.group(1).strip()
        else:  # 宣讲会的状态是内联样式 span（无 status-text 类）
            sm = re.search(r'<span style="[^"]*"[^>]*>(已举办|未开始|报名中|进行中)</span>', block)
            status = sm.group(1) if sm else ""
        tm = re.search(r'<span class="time">([^<]+)</span>', block)
        am = re.search(r'<span class="address">(?:<i[^>]*></i>)?([^<]+)</span>', block)
        vm = re.search(r'<span class="browse">.*?</i>(\d+)</span>', block, re.S)
        items.append(CareerItem(
            kind=kind, item_id=item_id, title=title,
            url=f"{CAREER_SITE_BASE}/{kind}/view/id/{item_id}",
            date=f"{month}.{day}", time=tm.group(1).strip() if tm else "",
            venue=am.group(1).strip() if am else "",
            status=status, views=vm.group(1) if vm else "",
        ))
    return items


def _fetch_home() -> str:
    session = http_session()
    session.trust_env = False  # 校方域名直连（本机代理不吃内网路由）
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
    )
    body, _etag = http_get_with_etag(
        f"{CAREER_SITE_BASE}/", cache_name="careersite/home.html", session=session
    )
    return body


def announcements(kind: str | None = None, keyword: str | None = None) -> list[CareerItem]:
    """首页三区块条目（可按类型/关键词过滤）。

    :param kind: ``campus``（招聘公告）/ ``jobfair``（招聘会）/ ``teachin``（宣讲会）。
    """
    try:
        html = _fetch_home()
    except Exception as exc:
        raise WestlakeError(f"就业服务网首页抓取失败：{exc.__class__.__name__}") from exc
    items = _parse_home(html)
    if not items:
        raise WestlakeError("就业服务网首页解析到 0 条——页面结构可能变化")
    if kind:
        items = [i for i in items if i.kind == kind]
    if keyword:
        kw = keyword.lower()
        items = [i for i in items if kw in i.title.lower() or kw in i.venue.lower()]
    return items


# --------------------------------------------------------------------------- #
# 登录态深列表 / 详情（2026-10-27 接入；IAM CAS 直连会话，无浏览器）
# --------------------------------------------------------------------------- #
#: 深列表支持的类型（news 为新闻资讯，详情是 ``/news/view/tag/<tag>`` 形态，
#: 见 discovery 缓存 content_career.json 的「招聘指南」链接）。
DEEP_KINDS = ("campus", "jobfair", "teachin", "news")

#: 各类型列表页路径（2026-10-27 实测匿名访问均重定向 IAM 登录）。
_LIST_PATH = {
    "campus": "/campus",
    "jobfair": "/jobfair",
    "teachin": "/teachin",
    "news": "/news",
}

#: news 资讯的 tag 索引（2026-10-27 匿名实测 news 子导航仅此两个，各自带
#: unzip 压缩列表；``/news`` 根页只有栏目导航、没有文章列表）。
_NEWS_TAGS = ("yxbys", "sysl")  # 毕业之后 / 生源速览

#: 详情链接形态：campus/jobfair/teachin 用 ``/view/id/<n>``；news 列表条目是
#: ``/news/view/aid/<n>/tag/<tag>``，另有 ``/news/view/tag/<tag>``（栏目页，
#: 2026-10-27 匿名实测 news 列表压缩块内锚点）。
_VIEW_LINK_RE = re.compile(
    r'<a\b[^>]*href="(?:https?://career\.westlake\.edu\.cn)?'
    r'(?P<path>/(?P<kind>campus|jobfair|teachin)/view/id/(?P<num>\d+)'
    r'|/news/view/(?P<npath>aid/(?P<aid>\d+)(?:/tag/[A-Za-z0-9_\-]+)?'
    r'|tag/[A-Za-z0-9_\-]+|id/\d+))"[^>]*>'
    r'(?P<inner>.*?)</a>',
    re.S,
)

#: 会话失效特征（2026-10-27 实测）：会话死了 GET 会逐跳 302 落到 IAM
#: ``/ac/`` Vue 壳（6302 字节，唯一可靠标记 ``id="index-loading"``）；
#: ``name="execution"`` 兜底经典 CAS 表单。**不要**用 ``/user/login`` 或
#: ``iam.westlake.edu.cn`` 当标记——前者是跳转目标不渲染、正常页可能带链接，
#: 后者登录页正文里没有、正常页反而可能有外链，都会误杀。
_LOGIN_MARKERS = ('id="index-loading"', 'name="execution"')

#: 首页同款 UA（匿名块实测可用）。
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
)

#: 登录态会话（进程内单例，taskcenter 同款）。
_SESSION = None

#: 进程内登录失败记忆：4333 风控态下同一进程绝不发起第二次 IAM 尝试。
_AUTH_FAILED: str | None = None


def _deep_session():
    """返回已登录就业服务网的 :class:`requests.Session`（惰性，一次登录）。

    登录链路（2026-10-27 实测）：``GET /campus`` 逐跳 302 落到
    ``iam.../ac/#/index?lck=context_CAS_…&entityId=https://career.westlake.edu.cn``，
    :func:`westlake_survival.iam.login_for` 按该形态解析 lck/entityId 完成认证
    并跟回 career 建会话。凭据缺失抛 :class:`AuthError`；IAM 拒绝（含 4333
    风控态）同样抛 :class:`AuthError` 并记入进程内失败记忆，不二次尝试。
    """
    global _SESSION, _AUTH_FAILED
    if _AUTH_FAILED is not None:
        raise AuthError(_AUTH_FAILED)
    if _SESSION is None:
        from westlake_survival import iam
        from westlake_survival.sso import read_credentials

        try:
            sid, password = read_credentials()
        except Exception as exc:
            raise AuthError("未配置统一凭据；先 westlake sso creds set 或在网页「设置」页配置") from exc
        try:
            _SESSION = iam.login_for(f"{CAREER_SITE_BASE}{_LIST_PATH['campus']}", sid, password)
        except AuthError as exc:
            _AUTH_FAILED = str(exc)  # 风控/密码错误都不给第二次机会
            raise
        _SESSION.headers.setdefault("User-Agent", _UA)
    return _SESSION


def _looks_logged_out(body: str) -> bool:
    return any(marker in body for marker in _LOGIN_MARKERS)


def _fetch_logged(path: str, cache_name: str, *, public: bool = False) -> str:
    """登录态 GET 一个 career 页面（ETag 缓存），返回 HTML。

    会话失效时（响应是登录页）重登一次再试；仍失效抛 :class:`AuthError`。
    ``public=True``（news 列表/详情页，2026-10-27 匿名 200 实测公开）在登录
    被风控/凭据缺失挡住时降级为匿名会话直取——拿到登录页才照常抛错。
    """
    global _SESSION

    def _get(session) -> str:
        try:
            body, _etag = http_get_with_etag(
                f"{CAREER_SITE_BASE}{path}", cache_name=cache_name, session=session
            )
        except requests.RequestException as exc:
            raise WestlakeError(
                f"就业服务网请求失败：{exc.__class__.__name__}（DNS/断网/代理劫持均会这样，"
                "网络一律直连，先排查本机网络）"
            ) from exc
        return body

    try:
        for attempt in (0, 1):
            session = _deep_session()
            body = _get(session)
            if not _looks_logged_out(body):
                return body
            _SESSION = None
            if attempt == 0:
                continue
        raise AuthError("就业服务网会话已失效（重登后仍是登录页），请稍后重试。")
    except AuthError:
        if not public:
            raise
        session = http_session()
        session.headers.setdefault("User-Agent", _UA)
        body = _get(session)
        if not _looks_logged_out(body):
            return body
        raise


def _payload_parts(html: str) -> list[str]:
    """解开页面内嵌的 ``unzip("…")`` 压缩块，返回「原 HTML, 各解压内容」分段。

    站点机制（2026-10-27 匿名实测 news 列表与详情页）：正文不在 SSR 明文里，
    而是内嵌为 ``Base64.decode(unzip("eJz…"))``——zlib 解压后形如
    ``view2d<空格><base64>``，``viewNd`` 是嵌套深度标记，逐层去标记 + base64
    解码，最内层才是列表 HTML、正文段落或跳转 URL（news aid 详情页是 320
    字节的 ``window.location=…`` 跳转壳，解出真实地址）。任何一层解不开就停
    在该层。
    """
    parts = [html]
    for payload in re.findall(r'unzip\("([A-Za-z0-9+/=]+)"\)', html):
        try:
            text = zlib.decompress(base64.b64decode(payload)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - 非 zlib/非 base64 的 unzip 调用跳过
            continue
        for _ in range(8):
            marker = re.match(r"\s*view(\d+)d\s*(.*)", text, re.S)
            if not marker:
                break
            rest = marker.group(2).strip()
            try:
                text = base64.b64decode(rest, validate=True).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - 已是明文（HTML/URL），最后一层
                text = rest
                break
        parts.append(text)
    return parts


def _unwrap_payloads(html: str) -> str:
    """:func:`_payload_parts` 的拼接形态（列表解析用）。"""
    return "\n".join(_payload_parts(html))


def _parse_deep(html: str) -> list[CareerItem]:
    """从（已解压的）列表内容抽条目，沿用 _parse_home 的锚点解析风格。

    日期取条目锚点前最近的一个 ``2026-08-27`` 形态文本（news 列表实测每条
    前置 ``<li class="span2 y">日期</li>``；campus 列表结构未登录态实测前
    不臆断，抽不到就留空）。
    """
    items: list[CareerItem] = []
    seen: set[tuple[str, str]] = set()
    for m in _VIEW_LINK_RE.finditer(html):
        kind, num, npath, aid, inner = (
            m.group("kind"),
            m.group("num"),
            m.group("npath"),
            m.group("aid"),
            m.group("inner"),
        )
        if kind:
            item_id, url = num, f"{CAREER_SITE_BASE}/{kind}/view/id/{num}"
        else:
            kind = "news"
            if aid:
                item_id = aid
            else:
                id_m = re.search(r"(?:aid|id)/(\d+)|tag/([A-Za-z0-9_\-]+)", npath)
                item_id = (id_m.group(1) or id_m.group(2)) if id_m else npath
            url = f"{CAREER_SITE_BASE}/news/view/{npath}"
        key = (kind, item_id)
        if key in seen:
            continue
        title_attr = re.search(r'title="([^"]*)"', m.group(0))
        # 状态徽标嵌在 <a> 内（首页教训），先摘掉再取纯文本
        inner_clean = re.sub(
            r'<span[^>]*>(?:已举办|未开始|报名中|进行中)</span>', "", inner
        )
        title = (title_attr.group(1) if title_attr else _strip_tags(inner_clean)).strip()
        if not title:
            continue
        seen.add(key)
        lookback = html[max(0, m.start() - 300) : m.start()]
        date_m = re.findall(r"(20\d\d[-/.]\d{1,2}[-/.]\d{1,2})", lookback)
        items.append(
            CareerItem(
                kind=kind, item_id=item_id, title=title, url=url,
                date=date_m[-1] if date_m else "",
            )
        )
    return items


def deep(kind: str, page: int = 1) -> list[CareerItem]:
    """登录态深列表（列表内容为 unzip 压缩块内嵌，见 :func:`_unwrap_payloads`）。

    :param kind: ``campus`` / ``jobfair`` / ``teachin`` / ``news``。
    :param page: 页码（>=1）；第 1 页取列表路径本身，之后拼 ``?page=N``
        （Yii 分页约定推测，2026-10-27 匿名 news 单页无法验证，campus 登录态
        首跑为准）。
    :returns: :class:`CareerItem` 列表（含日期，压缩块内实测可得）。

    Raises:
        AuthError: 未配置凭据 / IAM 拒绝（含 4333 风控态）/ 会话失效。
        ParseError: 解压后仍解析到 0 条（末页或结构变化），绝不静默返回空。
    """
    if kind not in _LIST_PATH:
        raise WestlakeError(f"未知的列表类型：{kind}（可选 {', '.join(DEEP_KINDS)}）")
    page = max(1, int(page))
    suffix = "" if page == 1 else f"?page={page}"
    if kind == "news":
        paths = [f"/news/index/tag/{t}{suffix}" for t in _NEWS_TAGS]
    else:
        paths = [f"{_LIST_PATH[kind]}{suffix}"]
    html = "\n".join(
        _fetch_logged(p, f"careersite/deep_{kind}_{i}_p{page}.html",
                      public=(kind == "news"))
        for i, p in enumerate(paths)
    )
    items = _parse_deep(_unwrap_payloads(html))
    if kind == "news":
        # news 列表页的子导航（招聘指南/中心介绍…）也是 news/view/tag 形态，
        # 会混进条目：有 aid 数字条目（真实列表项，带日期）时丢弃导航项。
        aid_items = [i for i in items if i.item_id.isdigit()]
        if aid_items:
            items = aid_items
    if not items:
        if "unzip(" not in html:
            raise ParseError(
                f"就业服务网 {kind} 列表第 {page} 页没有内嵌压缩内容块，解析到 0 条"
                "——页面结构可能变化，请反馈。"
            )
        raise ParseError(
            f"就业服务网 {kind} 列表第 {page} 页解压后仍解析到 0 条——可能已到末页"
            "或条目锚点形态变化，请反馈。"
        )
    return items


@dataclass
class CareerDetail:
    """就业服务网一条详情（详情页可能 SSR 正文，也可能是跳转壳）。"""

    kind: str
    item_id: str
    title: str
    url: str
    date: str = ""  # 正文中识别到的发布日期（2026-10-27 形态）
    body: str = ""  # 纯文本正文（去标签、压空白）
    attachments: list = field(default_factory=list)  # [{"name":…, "url":…}]
    note: str = ""  # 解析说明（如「详情为外部文章链接」）；正常 SSR 为空

    @property
    def kind_label(self) -> str:
        return _KIND_LABEL.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "kind_label": self.kind_label,
            "id": self.item_id,
            "title": self.title,
            "url": self.url,
            "date": self.date,
            "body": self.body,
            "attachments": self.attachments,
            "note": self.note,
        }


def detail(ref: str) -> CareerDetail:
    """取一条详情（需登录）。

    详情页形态（2026-10-27 实测）：campus/jobfair/teachin 为 SSR 页；
    news 是约 320 字节的 ``window.location=Base64.decode(unzip(…))`` 跳转壳，
    解开得到真实地址——站内地址则跟进再解析，外站（实测为微信公众号文章
    mp.weixin.qq.com）如实返回链接与说明，不臆造正文。

    :param ref: 数字 id（``1129108``）、news aid/tag、或完整 URL——与
        :func:`deep` 输出的 ``url`` / ``id`` 对应。
    """
    ref = (ref or "").strip()
    if not ref:
        raise WestlakeError("请提供详情 id 或 URL（来自 career deep 列表输出）")
    match = re.search(
        r"career\.westlake\.edu\.cn/(?:(campus|jobfair|teachin)/view/id/(\d+)"
        r"|news/view/(aid/(\d+)(?:/tag/[A-Za-z0-9_\-]+)?|tag/([A-Za-z0-9_\-]+)|id/(\d+)))",
        ref,
    )
    if ref.isdigit() and not match:
        # 纯数字 id：类型未知，依次试四类详情（news 的 /view/aid/<n> 无 tag
        # 也可达，2026-10-27 匿名实测 316 字节跳转壳；news 公开放最后）。
        # 登录类失败（风控/凭据）先记住，news 公开回退跑完仍无果再原样抛出。
        auth_error: AuthError | None = None
        for kind, path_tpl, public in (
            ("campus", "/campus/view/id/{ref}", False),
            ("jobfair", "/jobfair/view/id/{ref}", False),
            ("teachin", "/teachin/view/id/{ref}", False),
            ("news", "/news/view/aid/{ref}", True),
        ):
            try:
                parsed = _detail_fetch(
                    path_tpl.format(ref=ref), f"careersite/detail_{kind}_{ref}.html",
                    kind=kind, item_id=ref, depth=0, public=public,
                )
            except AuthError as exc:
                auth_error = exc
                continue
            if parsed is not None:
                return parsed
        if auth_error is not None:
            raise auth_error
        raise ParseError(f"详情 {ref} 在四类详情页中都解析失败——id 可能不存在")
    if match:
        if match.group(1):
            kind = match.group(1)
            item_id = match.group(2)
            path = f"/{kind}/view/id/{item_id}"
        else:
            kind = "news"
            npath = match.group(3)
            item_id = match.group(4) or match.group(5) or match.group(6) or ""
            path = f"/news/view/{npath}"
    else:
        kind, item_id, path = "news", ref, f"/news/view/tag/{ref}"
    parsed = _detail_fetch(path, f"careersite/detail_{kind}_{item_id}.html",
                           kind=kind, item_id=item_id, depth=0,
                           public=(kind == "news"))
    if parsed is None:
        raise ParseError(
            f"详情页 {CAREER_SITE_BASE}{path} 解析失败——页面结构可能变化，或条目不存在"
        )
    return parsed


def _detail_fetch(path: str, cache_name: str, *, kind: str, item_id: str,
                  depth: int, public: bool = False) -> "CareerDetail | None":
    """抓一个详情路径并解析；跳转壳解出站内地址时递归跟进（≤3 层）。

    ``public``（news 详情页公开，匿名 200 实测）透传 :func:`_fetch_logged`，
    登录被风控挡住时降级匿名抓取。
    """
    html = _fetch_logged(path, cache_name, public=public)
    content = "\n".join(_payload_parts(html))
    url = f"{CAREER_SITE_BASE}{path}"
    # 跳转壳：整页只有一段 window.location=Base64.decode(unzip(…)) 脚本
    if len(html) < 2000 and "window.location" in html and "unzip(" in html:
        target_m = re.search(r"(https?://[^\s\"'<>]+)", content)
        if target_m:
            target = target_m.group(1)
            host = urlparse(target).netloc
            if host in ("career.westlake.edu.cn",) and depth < 3:
                inner_path = target.split("career.westlake.edu.cn", 1)[1]
                inner_id = re.search(r"/view/(?:id|aid)/(\d+)", inner_path)
                return _detail_fetch(
                    inner_path, f"careersite/detail_{kind}_{inner_id.group(1) if inner_id else item_id}.html",
                    kind=kind, item_id=inner_id.group(1) if inner_id else item_id, depth=depth + 1,
                    public=public,
                )
            return CareerDetail(
                kind=kind, item_id=item_id, title="", url=target, date="",
                body="", attachments=[],
                note="详情为外部文章链接（就业站把正文托管在外部），本命令不抓取外部正文",
            )
    return _parse_detail(_payload_parts(html), kind, item_id, url)


def _parse_detail(parts: list[str], kind: str, item_id: str, url: str) -> "CareerDetail | None":
    """从详情页分段（原 HTML + 解压载荷）抽标题 / 日期 / 正文 / 附件。

    页面结构（2026-10-27 实测 news 栏目页）：原 HTML 的 ``id="mn"`` 容器只有
    标题与 meta 条，正文段落在压缩载荷里（裸 ``<p>`` 片段）。逐段取正文范围：
    带 mn 容器的段从容器开标签切到 css-footer 之前（切界落在标签属性中间时
    截掉未闭合残片），纯 ``<p>`` 载荷段整段算正文；拼接后统一去标签。
    """
    scopes: list[str] = []
    for part in parts:
        scope_m = re.search(r'class="mn[^"]*(?:view|details)[^"]*"', part)
        if scope_m:
            div_start = part.rfind("<div", 0, scope_m.start())
            scope = part[div_start:] if div_start >= 0 else part[scope_m.start():]
            footer = scope.find('class="css-footer"')
            if footer > 0:
                scope = scope[:footer]
            if scope.rfind("<") > scope.rfind(">"):
                scope = scope[: scope.rfind("<")]
            scopes.append(scope)
        elif scopes and re.search(r"<p\b", part, re.I):
            scopes.append(part)  # 压缩载荷里的正文段落片段
    html = "\n".join(parts)
    if not scopes:
        # 没有任何 mn 容器：站点对不存在的条目返回通用模板页（<title> 是
        # 站点名、正文全是导航壳，2026-10-27 实测）——不当作详情解析，返回
        # None 让调用方继续尝试或报错；其余未知结构仍宽松解析。
        title_m = re.search(r"<title>([^<]*)</title>", html)
        if title_m and title_m.group(1).strip().startswith("西湖大学就业服务网"):
            return None
        scope = html
    else:
        scope = "\n".join(scopes)
    scope = re.sub(r"<script\b.*?</script>", " ", scope, flags=re.S | re.I)
    scope = re.sub(r"<style\b.*?</style>", " ", scope, flags=re.S | re.I)

    title = ""
    title_m = re.search(r"<h\d[^>]*>(.*?)</h\d>", scope, re.S)
    if title_m:
        title = _strip_tags(title_m.group(1))
    if not title:
        title_m = re.search(r"<title>([^<]*)</title>", html)
        if title_m:
            title = _strip_tags(title_m.group(1))
    date = ""
    date_m = re.search(r"(20\d\d[-/.]\d{1,2}[-/.]\d{1,2})", scope)
    if date_m:
        date = date_m.group(1)

    attachments = []
    for am in re.finditer(
        r'<a\b[^>]*href="([^"]*(?:/attachment/|\.pdf|\.docx?|\.xlsx?)[^"]*)"[^>]*>(.*?)</a>',
        scope,
        re.S | re.I,
    ):
        href = am.group(1)
        if href.startswith("/"):
            href = CAREER_SITE_BASE + href
        name = _strip_tags(am.group(2)) or href.rsplit("/", 1)[-1]
        attachments.append({"name": name, "url": href})

    # 正文：容器内纯文本（导航壳已在 scope 之外；不做词级删改，避免误伤正文）
    text = _strip_tags(scope)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 40:  # 没有可读正文（结构变化）
        return None
    if len(text) > 6000:
        text = text[:6000] + "…"
    return CareerDetail(
        kind=kind, item_id=item_id, title=title, url=url, date=date,
        body=text, attachments=attachments,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli():
    import functools

    import click

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    @click.group(name="career", help="就业服务网：三区块免登录 + 登录态深列表/详情。")
    def group() -> None:
        """``westlake career list``；深列表 ``westlake career deep``。"""

    @group.command(name="list")
    @click.option("-k", "--kind", default=None,
                  type=click.Choice(["campus", "jobfair", "teachin"]),
                  help="campus=招聘公告 jobfair=招聘会 teachin=宣讲会；缺省全部")
    @click.option("--keyword", "-q", default=None, help="标题/场地子串过滤")
    @handle
    def list_cmd(kind: str | None, keyword: str | None) -> None:
        """首页三区块条目（免登录公开面）。"""
        items = announcements(kind, keyword)
        if not items:
            click.echo("没有匹配的条目。")
            return
        for it in items:
            extra = " ".join(x for x in (it.status, it.time, it.venue) if x)
            click.echo(f"  [{it.kind_label}] {it.date} {it.title}" + (f"（{extra}）" if extra else ""))
            click.echo(f"    {it.url}")

    @group.command(name="deep")
    @click.option("-k", "--kind", default="campus", show_default=True,
                  type=click.Choice(DEEP_KINDS),
                  help="campus=招聘公告 jobfair=招聘会 teachin=宣讲会 news=新闻资讯")
    @click.option("--page", type=int, default=1, show_default=True, help="页码（>=1）")
    @handle
    def deep_cmd(kind: str, page: int) -> None:
        """登录态深列表（全量分页；统一密码，自动登录）。"""
        items = deep(kind, page)
        click.echo(f"共 {len(items)} 条（{kind} 第 {page} 页）：")
        for it in items:
            head = f"  {it.item_id}\t{it.date} {it.title}" if it.date else f"  {it.item_id}\t{it.title}"
            click.echo(head)
            click.echo(f"    {it.url}")

    @group.command(name="detail")
    @click.argument("ref")
    @handle
    def detail_cmd(ref: str) -> None:
        """详情页正文（REF 为列表输出的 id / URL / news aid 或 tag）。"""
        d = detail(ref)
        click.echo(f"标题：{d.title or '—'}")
        click.echo(f"类型：{d.kind_label}　id：{d.item_id}")
        if d.date:
            click.echo(f"日期：{d.date}")
        click.echo(f"链接：{d.url}")
        if d.note:
            click.echo(f"说明：{d.note}")
        for att in d.attachments:
            click.echo(f"附件：{att['name']}\n    {att['url']}")
        if d.body:
            click.echo("正文：")
            click.echo(d.body)
        elif not d.note:
            click.echo("正文：（站内页面未解析到正文，见上方链接）")

    return group


cli_group = _cli()
