"""官网「餐饮住宿」模块：食堂、咖啡轻食、公寓与校园服务。

数据源是学校官网「校园生活 / 餐饮住宿」页面
``https://www.westlake.edu.cn/campus_life/housing_dining/``（2026-09-22 实测）。
该页是 Vue 单页应用，真实数据内嵌在 ``new housingDining("#app", { ... })``
调用里，键 ``allData`` 是一个数组，每项形如::

    {
      keyword: "住宿" | "食堂" | "咖啡轻食" | "其他校园服务" | "交通方式",
      type: "0"(卡片) | "1"(表格),
      data: [ { label: "云谷校区", list: [ {...}, ... ] }, ... ],
    }

- 食堂 / 咖啡轻食条目：``{imgUrl, name, address, food, date}``，其中 ``date``
  是营业时间 HTML（``<br/>``、``</br>``、``<br>`` 或 ``</p><p>`` 分行）。
- 住宿条目：``{imgUrl, name, address, date, phone}``，``date`` 里是管家服务、
  房型与公寓配套等服务信息（同样按 HTML 换行分行）。
- 其他校园服务条目：与食堂同构，``date`` 是营业时间。

**班车「交通方式」部分不在此模块解析**——现有 :mod:`westlake_survival.transit`
已覆盖时刻表；本模块只把它 ``notice`` 里的班车实时信息外链抽成常量
:data:`SHUTTLE_LIVE_URL`。

实测坑位
========
- 组件对象里混有 ``mounted: function () {}`` 回调，**不能对整块调用**
  :func:`~westlake_survival._trs.js_literal`；先用
  :func:`~westlake_survival._trs.component_script` 取出对象文本，再按键
  ``allData`` 截出数组后只解析数组。
- 响应 ``Content-Type: text/html`` **不带 charset**，``requests`` 会按
  ISO-8859-1 解码，``response.text`` 得到乱码；本模块一律取
  ``response.content`` 手动 UTF-8 解码。

查询类接口每次调用都真发请求（默认进程内单例缓存，``load(refresh=True)``
强制重取）。

双语源（lang 参数）
==================
``lang="en"`` 抓英文主站 en.westlake.edu.cn 同路径页面（2026-10-24 实测）：
英文页数据块 ``keyword`` 与校区标签都是英文，分块结构与中文不同（无「住宿」
块、餐饮拆成两块、超市与按校区名分块的服务块并存）。归类规则：keyword 命中
:data:`DINING_KINDS_EN` 归餐饮、含 "housing/apartment/residence" 片段归住宿、
含 "shuttle" 片段只保留 notice（时刻表由 :mod:`westlake_survival.transit`
负责）、**其余 type-0 块一律原样透传为其他校园服务**；校区标签与 kind 均保留
英文原始值（如 ``"Yungu Campus"``），不做中文归一，因此 ``dining`` /
``housing`` / ``services`` 的 ``campus`` / ``kind`` 过滤在 en 模式下须传英文
原始值。:meth:`CampusData.shuttle_notice` 仍按中文 keyword 取值，en 数据上
返回空串（en 班车 notice 请直接读 :attr:`CampusData.notices`）。
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

import click
import requests

from westlake_survival._cache import load_json, save_json
from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival._trs import array_of, component_script
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError, is_offcampus

__all__ = [
    "HOUSING_DINING_URL",
    "CACHE_NAME",
    "SHUTTLE_LIVE_URL",
    "DINING_KINDS",
    "DINING_KINDS_EN",
    "HOUSING_KEYWORD",
    "SERVICES_KEYWORD",
    "SHUTTLE_KEYWORD",
    "CAMPUS_CHOICES",
    "CAMPUS_CHOICES_EN",
    "DiningSpot",
    "Housing",
    "CampusService",
    "CampusData",
    "parse_campus",
    "load",
    "dining",
    "housing",
    "services",
    "cli_group",
]

#: 「餐饮住宿」页面 URL。
HOUSING_DINING_URL = "https://www.westlake.edu.cn/campus_life/housing_dining/"

#: ETag 缓存文件名（相对缓存目录）。与 transit 共用同一页面，但各存一份，
#: 避免两模块的解析口径相互影响。
CACHE_NAME = "campus/housing_dining.html"

#: 双语源（2026-10-24 实测）：英文主站 en.westlake.edu.cn 同路径同组件名，
#: 但英文页数据块的 ``keyword`` 与校区标签都是英文，且分块结构与中文不同：
#: 没有「住宿」块；餐饮拆成 ``"Dining Halls"`` / ``"Bakeries"`` 两块；超市
#: （``"Convenience Stores"``）与按校区名分块的银行/邮局/理发等归入其他校园
#: 服务；班车为 ``"Workday/Weekend Shuttle Bus Schedule"`` 两块（只取 notice）。
HOUSING_DINING_URLS = {
    "zh": HOUSING_DINING_URL,
    "en": "https://en.westlake.edu.cn/campus_life/housing_dining/",
}

#: ETag 缓存文件名（按语言；zh 缓存名逐字保留，en 另存一份避免互相覆盖）。
CACHE_BY_LANG = {"zh": CACHE_NAME, "en": "campus/housing_dining_en.html"}

#: 班车实时信息外链（取自页面「交通方式」块 ``notice`` 的 ``<a href>``）。
#: 交通方式本身由 :mod:`westlake_survival.transit` 提供，此处仅保留外链。
SHUTTLE_LIVE_URL = "https://security.zjwsvip.com/#/h5shuttleRoute/1906876984879099905"

#: ``allData`` 里餐饮类数据块的关键词（即 ``dining`` 的 ``kind`` 取值）。
DINING_KINDS = ("食堂", "咖啡轻食")

#: 英文页餐饮数据块的 keyword 实测值（``lang="en"`` 时 ``dining`` 的 ``kind``
#: 取值，原样透传英文值）。
DINING_KINDS_EN = ("Dining Halls", "Bakeries")

#: ``allData`` 里住宿数据块的关键词。
HOUSING_KEYWORD = "住宿"

#: 英文页住宿数据块 keyword 的匹配片段（小写子串匹配；当前英文页未提供住宿
#: 块，预留以便页面补充后自动归入 :attr:`CampusData.housing`）。
_HOUSING_KEYWORD_EN_FRAGMENTS = ("housing", "apartment", "residence")

#: 英文页班车数据块 keyword 的共同片段（小写子串匹配；本模块不解析其时刻表，
#: 只保留 ``notice``）。
_SHUTTLE_KEYWORD_EN_FRAGMENT = "shuttle"

#: ``allData`` 里其他校园服务数据块的关键词。
SERVICES_KEYWORD = "其他校园服务"

#: ``allData`` 里班车数据块的关键词（本模块不解析其时刻表，只取外链）。
SHUTTLE_KEYWORD = "交通方式"

#: CLI ``--campus`` 可选值（住宿/餐饮数据里出现的校区）。
CAMPUS_CHOICES = ("云谷", "云栖")

#: CLI ``--campus`` 的英文校区可选值（``lang="en"`` 数据里的原始标签）。
CAMPUS_CHOICES_EN = ("Yungu Campus", "Yunqi Campus")

#: 校区标签统一去掉的尾缀（页面 ``label`` 形如 ``"云谷校区"``）。
_CAMPUS_SUFFIX = "校区"

#: 换行标记：``<br>`` / ``<br/>`` / ``<br />`` / ``</br>``，以及段落边界
#: ``</p><p>``（咖啡吧的两段营业时间即以此分隔）。
_LINE_BREAK_RE = re.compile(
    r"<\s*br\s*/?\s*>|</\s*br\s*>|</\s*p\s*>\s*<\s*p[^>]*>",
    re.IGNORECASE,
)

#: 任意 HTML 标签（用于把 ``date`` 里的 ``<span>``、``<p>`` 等剥掉）。
_TAG_RE = re.compile(r"<[^>]*>")

#: ``href="..."`` 属性（单/双引号）。
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class DiningSpot:
    """一个餐饮点：食堂或咖啡轻食。

    ``hours`` 是营业时间逐行拆出的纯文本（已剥掉 HTML 标签）；``food`` 是
    供餐内容（咖啡轻食多为空串）。
    """

    name: str
    campus: str
    address: str = ""
    food: str = ""
    hours: list[str] = field(default_factory=list)


@dataclass
class Housing:
    """一处公寓。

    ``services`` 是服务/房型/配套信息逐行拆出的纯文本；``phone`` 是联系电话
    （页面多数为空串）。
    """

    name: str
    campus: str
    address: str = ""
    services: list[str] = field(default_factory=list)
    phone: str = ""


@dataclass
class CampusService:
    """一项其他校园服务（超市、快递驿站、理发、银行等）。"""

    name: str
    campus: str
    address: str = ""
    hours: list[str] = field(default_factory=list)


@dataclass
class CampusData:
    """整页「餐饮住宿」数据。

    ``dining`` 以 ``kind``（:data:`DINING_KINDS` 之一）为键；``notices`` 保留各
    数据块原始的 ``notice`` HTML（供展示反馈文案），键为数据块 ``keyword``。
    """

    dining: dict[str, list[DiningSpot]] = field(default_factory=dict)
    housing: list[Housing] = field(default_factory=list)
    services: list[CampusService] = field(default_factory=list)
    notices: dict[str, str] = field(default_factory=dict)

    def shuttle_notice(self) -> str:
        """返回「交通方式」块的原始 ``notice`` HTML（含班车实时信息外链）。"""
        return self.notices.get(SHUTTLE_KEYWORD, "")


# --------------------------------------------------------------------------- #
# 文本工具
# --------------------------------------------------------------------------- #
def _split_lines(html_text: str) -> list[str]:
    """把一段含 HTML 的文本按换行标记拆成纯文本行。

    先按 ``<br>`` 系列与 ``</p><p>`` 换成 ``\\n``，再剥掉其余标签，最后逐行
    去空白并丢弃空行。空输入返回空列表。
    """
    if not html_text:
        return []
    text = _LINE_BREAK_RE.sub("\n", html_text)
    text = _TAG_RE.sub("", text)
    return [line.strip() for line in text.split("\n") if line.strip()]


def _normalize_campus(label: str) -> str:
    """把校区标签统一成简称：``"云谷校区"`` → ``"云谷"``。"""
    label = (label or "").strip()
    if label.endswith(_CAMPUS_SUFFIX):
        return label[: -len(_CAMPUS_SUFFIX)]
    return label


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _iter_groups(section: dict) -> list[tuple[str, list[dict]]]:
    """把某数据块的 ``data`` 拆成 ``[(校区, [条目, ...]), ...]``。

    结构不符（``data`` 不是数组、条目不是对象）时跳过，保持容错。
    """
    groups: list[tuple[str, list[dict]]] = []
    raw_groups = section.get("data")
    if not isinstance(raw_groups, list):
        return groups
    for group in raw_groups:
        if not isinstance(group, dict):
            continue
        campus = _normalize_campus(str(group.get("label") or ""))
        items = [item for item in (group.get("list") or []) if isinstance(item, dict)]
        groups.append((campus, items))
    return groups


def _parse_dining(section: dict) -> list[DiningSpot]:
    """把一个餐饮数据块解析成 :class:`DiningSpot` 列表。"""
    spots: list[DiningSpot] = []
    for campus, items in _iter_groups(section):
        for item in items:
            spots.append(
                DiningSpot(
                    name=str(item.get("name") or ""),
                    campus=campus,
                    address=str(item.get("address") or ""),
                    food=str(item.get("food") or ""),
                    hours=_split_lines(str(item.get("date") or "")),
                )
            )
    return spots


def _parse_housing(section: dict) -> list[Housing]:
    """把住宿数据块解析成 :class:`Housing` 列表。"""
    houses: list[Housing] = []
    for campus, items in _iter_groups(section):
        for item in items:
            houses.append(
                Housing(
                    name=str(item.get("name") or ""),
                    campus=campus,
                    address=str(item.get("address") or ""),
                    services=_split_lines(str(item.get("date") or "")),
                    phone=str(item.get("phone") or ""),
                )
            )
    return houses


def _parse_services(section: dict) -> list[CampusService]:
    """把「其他校园服务」数据块解析成 :class:`CampusService` 列表。"""
    services: list[CampusService] = []
    for campus, items in _iter_groups(section):
        for item in items:
            services.append(
                CampusService(
                    name=str(item.get("name") or ""),
                    campus=campus,
                    address=str(item.get("address") or ""),
                    hours=_split_lines(str(item.get("date") or "")),
                )
            )
    return services


def parse_campus(html: str, lang: str = "zh") -> CampusData:
    """解析「餐饮住宿」页面 HTML，返回 :class:`CampusData`。

    ``lang="zh"``（默认）按中文 keyword（:data:`DINING_KINDS` / 
    :data:`HOUSING_KEYWORD` / :data:`SERVICES_KEYWORD` / :data:`SHUTTLE_KEYWORD`）
    归类；``lang="en"`` 按英文 keyword 归类并**原样透传英文值**（规则见模块
    docstring「双语源」一节）。

    页面结构不符（找不到 ``housingDining`` 组件或 ``allData``）时抛
    :class:`~westlake_survival.exceptions.ParseError`。
    """
    block = component_script(html, "housingDining")
    if not block:
        raise ParseError("页面中找不到 housingDining 组件，结构可能已变化")
    sections = array_of(block, "allData")

    if lang == "zh":
        data = CampusData(dining={kind: [] for kind in DINING_KINDS})
        for section in sections:
            if not isinstance(section, dict):
                continue
            keyword = str(section.get("keyword") or "")
            notice = section.get("notice")
            if notice is not None:
                data.notices[keyword] = str(notice)
            if keyword in DINING_KINDS:
                data.dining[keyword] = _parse_dining(section)
            elif keyword == HOUSING_KEYWORD:
                data.housing = _parse_housing(section)
            elif keyword == SERVICES_KEYWORD:
                data.services = _parse_services(section)
        return data

    # en：keyword / 校区标签为英文，按英文枚举归类；未命中的 type-0 块原样
    # 透传为其他校园服务（services），班车块只保留 notice。
    data = CampusData(dining={kind: [] for kind in DINING_KINDS_EN})
    for section in sections:
        if not isinstance(section, dict):
            continue
        keyword = str(section.get("keyword") or "")
        lowered = keyword.lower()
        notice = section.get("notice")
        if notice is not None:
            data.notices[keyword] = str(notice)
        if keyword in DINING_KINDS_EN:
            data.dining[keyword] = _parse_dining(section)
        elif any(fragment in lowered for fragment in _HOUSING_KEYWORD_EN_FRAGMENTS):
            data.housing.extend(_parse_housing(section))
        elif _SHUTTLE_KEYWORD_EN_FRAGMENT in lowered:
            pass  # 班车时刻表由 transit 模块负责，这里只保留上面的 notice
        else:
            data.services.extend(_parse_services(section))
    return data


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _decode_body(response: requests.Response) -> str:
    """取响应体并按 UTF-8 解码。

    页面无 charset 声明，``response.text`` 会得到 latin-1 乱码，因此一律读
    ``response.content`` 原始字节手动解码。
    """
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text 的替身对象
        return getattr(response, "text", "") or ""
    return raw.decode("utf-8", errors="replace")


def _check_response(response: requests.Response, url: str = HOUSING_DINING_URL) -> None:
    """把 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    if status == 403 and is_offcampus(response):
        raise OffCampusError("「餐饮住宿」页面拒绝访问（403）")
    if status >= 400:
        raise ParseError(f"「餐饮住宿」页面返回 HTTP {status}：{url}")


def _fetch_html(
    session: requests.Session | None,
    timeout: float | None,
    lang: str = "zh",
) -> str:
    """带 ETag 条件请求地抓取页面，返回 UTF-8 文本。

    ``lang`` 选择中/英文主站与对应缓存（未知值回退 zh）。缓存读写复用
    :mod:`westlake_survival._cache` 的 JSON 存储；响应体一律经
    :func:`_decode_body` 按 ``content`` 解码。
    """
    session = session if session is not None else http_session()
    cache_name = CACHE_BY_LANG.get(lang, CACHE_NAME)
    cached = load_json(cache_name, default=None) or {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}
    try:
        response = session.get(
            HOUSING_DINING_URLS.get(lang, HOUSING_DINING_URL),
            headers=headers,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except requests.Timeout as exc:
        raise WestlakeError(
            f"「餐饮住宿」页面请求超时（{timeout if timeout is not None else DEFAULT_TIMEOUT}s）"
        ) from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"「餐饮住宿」页面请求失败：{exc}") from exc

    status = getattr(response, "status_code", 200)
    if status == 304 and cached.get("body"):
        return cached["body"]
    _check_response(response, HOUSING_DINING_URLS.get(lang, HOUSING_DINING_URL))
    body = _decode_body(response)
    etag = getattr(response, "headers", {}).get("ETag")
    if etag:
        save_json(cache_name, {"etag": etag, "body": body})
    return body


#: 进程内单例缓存（zh 口径保持原变量名 ``_instance``，既有测试直接注入该属性）。
_instance: CampusData | None = None

#: 英文页（``lang="en"``）的进程内单例——zh / en 数据结构不同，分开缓存。
_en_instance: CampusData | None = None


def load(
    refresh: bool = False,
    *,
    session=None,
    timeout: float | None = None,
    lang: str = "zh",
) -> CampusData:
    """抓取并解析「餐饮住宿」页面，返回进程内单例 :class:`CampusData`。

    Args:
        refresh: 为 ``True`` 时忽略进程内单例，重新抓取解析。
        session: 可注入的 :class:`requests.Session`（测试用）；缺省用
            :func:`westlake_survival._net.http_session`。
        timeout: 请求超时（秒），缺省 :data:`~westlake_survival._net.DEFAULT_TIMEOUT`。
        lang: ``"zh"``（默认）中文主站；``"en"`` 英文主站——数据块的 keyword
            与校区标签为英文原样透传（未知值回退 zh；单例按语言各存一份，
            zh 仍落在 :data:`_instance`）。

    Raises:
        WestlakeError: 网络层失败（超时/连接错误等）。
        ParseError: HTTP 4xx/5xx，或页面结构与预期不符。
        OffCampusError: 被校外访问网关拦截（403 且命中阻断页特征）。
    """
    global _instance, _en_instance
    singleton = _instance if lang == "zh" else _en_instance
    if singleton is None or refresh or session is not None:
        data = parse_campus(_fetch_html(session, timeout, lang=lang), lang=lang)
        if session is None:
            if lang == "zh":
                _instance = data
            else:
                _en_instance = data
        return data
    return singleton


# --------------------------------------------------------------------------- #
# 查询 API
# --------------------------------------------------------------------------- #
def _filter_campus(items, campus: str | None):
    """按校区过滤（``None`` 表示不过滤；输入可带/不带 ``校区`` 尾缀）。"""
    if campus is None:
        return list(items)
    wanted = _normalize_campus(campus)
    return [item for item in items if item.campus == wanted]


def dining(
    kind: str | None = None, campus: str | None = None, *, lang: str = "zh"
) -> list[DiningSpot]:
    """返回餐饮点列表。

    Args:
        kind: ``lang="zh"`` 时为 ``"食堂"`` / ``"咖啡轻食"``（:data:`DINING_KINDS`）；
            ``lang="en"`` 时为英文页原始 keyword（:data:`DINING_KINDS_EN`，如
            ``"Dining Halls"``）；``None`` 都表示全部类别。
        campus: 校区过滤（zh 为 ``"云谷"`` / ``"云栖"``，可带 ``"校区"`` 尾缀；
            en 为英文原始标签，如 ``"Yungu Campus"``）；``None`` 表示全部校区。
        lang: ``"zh"``（默认）中文主站；``"en"`` 英文主站。

    Raises:
        ValueError: ``kind`` 不在该语言下的可选值里。
    """
    if lang == "zh":
        if kind is not None and kind not in DINING_KINDS:
            raise ValueError(f"kind 必须是 {DINING_KINDS} 之一，得到 {kind!r}")
        data = load()
        kinds = (kind,) if kind is not None else DINING_KINDS
    else:
        data = load(lang=lang)
        if kind is not None and kind not in data.dining:
            raise ValueError(
                f"lang={lang!r} 下 kind 必须是 {tuple(data.dining)} 之一，得到 {kind!r}"
            )
        kinds = (kind,) if kind is not None else tuple(data.dining)
    spots: list[DiningSpot] = []
    for k in kinds:
        spots.extend(_filter_campus(data.dining.get(k, []), campus))
    return spots


def housing(campus: str | None = None, *, lang: str = "zh") -> list[Housing]:
    """返回公寓列表；``campus`` 为 ``None`` 时返回全部校区。

    ``lang="en"`` 时校区标签是英文原始值（如 ``"Yungu Campus"``）；当前英文页
    未提供住宿块，返回空列表。
    """
    return _filter_campus(load(lang=lang).housing, campus)


def services(campus: str | None = None, *, lang: str = "zh") -> list[CampusService]:
    """返回其他校园服务列表；``campus`` 为 ``None`` 时返回全部校区。

    ``lang="en"`` 时英文页的超市/银行/邮局/理发等块（含按校区名分块的）都归入
    此处，校区标签原样透传英文值。
    """
    return _filter_campus(load(lang=lang).services, campus)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    """装饰器：把 :class:`WestlakeError` 转成中文提示 + 退出码 1。

    与 :func:`westlake_survival.cli.main._handle_errors` 同款；此处自带一份
    以免与 ``cli.main`` 形成循环导入。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            if isinstance(exc, OffCampusError):
                click.secho(
                    "提示：该服务仅校园网/VPN 内可达，请先连接西湖大学 VPN："
                    "https://vpn.westlake.edu.cn/",
                    err=True,
                )
            raise SystemExit(1) from exc

    return wrapper


def _lang_kwargs(lang: str) -> dict:
    """把 ``lang`` 转成查询 API 的关键字参数；缺省 ``"zh"`` 时不传。

    ``dining`` / ``housing`` / ``services`` 的既有测试桩按原签名（不含
    ``lang``）打桩，zh 调用保持原形态，仅 ``lang="en"`` 时显式传参。
    """
    return {} if lang == "zh" else {"lang": lang}


@click.group(name="campus", help="校园生活：食堂 / 咖啡轻食 / 公寓。")
def cli_group() -> None:
    """``westlake campus`` 命令组。"""


@cli_group.command(name="dining")
@click.option(
    "--campus",
    type=click.Choice((*CAMPUS_CHOICES, *CAMPUS_CHOICES_EN)),
    default=None,
    help="只看某校区（zh：云谷/云栖；en：Yungu Campus/Yunqi Campus）。",
)
@click.option(
    "--kind",
    type=click.Choice((*DINING_KINDS, *DINING_KINDS_EN)),
    default=None,
    help="只看某类餐饮点（zh：食堂/咖啡轻食；en：Dining Halls/Bakeries）；缺省全部。",
)
@click.option(
    "--lang",
    type=click.Choice(["zh", "en"]),
    default="zh",
    show_default=True,
    help="语言：zh=中文主站 en=英文主站（kind/campus 用英文原始值）。",
)
@_handle_errors
def campus_dining(campus: str | None, kind: str | None, lang: str) -> None:
    """列出食堂 / 咖啡轻食（含营业时间）。"""
    from westlake_survival.cli.main import _print_table

    spots = dining(kind=kind, campus=campus, **_lang_kwargs(lang))
    if not spots:
        click.echo("未找到匹配的餐饮点。")
        return
    rows = [
        (
            spot.campus or "—",
            spot.name or "—",
            spot.address or "—",
            spot.food or "—",
            "；".join(spot.hours) or "—",
        )
        for spot in spots
    ]
    _print_table(rows, ("校区", "名称", "位置", "供餐", "营业时间"))


@cli_group.command(name="housing")
@click.option(
    "--campus",
    type=click.Choice((*CAMPUS_CHOICES, *CAMPUS_CHOICES_EN)),
    default=None,
    help="只看某校区（zh：云谷/云栖；en：Yungu Campus/Yunqi Campus）。",
)
@click.option(
    "--lang",
    type=click.Choice(["zh", "en"]),
    default="zh",
    show_default=True,
    help="语言：zh=中文主站 en=英文主站（campus 用英文原始值）。",
)
@_handle_errors
def campus_housing(campus: str | None, lang: str) -> None:
    """列出公寓（含服务与配套信息）。"""
    from westlake_survival.cli.main import _print_table

    houses = housing(campus=campus, **_lang_kwargs(lang))
    if not houses:
        click.echo("未找到匹配的公寓。")
        return
    rows = [
        (
            house.campus or "—",
            house.name or "—",
            house.address or "—",
            house.phone or "—",
            "；".join(house.services) or "—",
        )
        for house in houses
    ]
    _print_table(rows, ("校区", "名称", "位置", "电话", "服务/配套"))