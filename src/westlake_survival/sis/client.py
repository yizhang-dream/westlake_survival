"""SIS 客户端：课表抓取、xls 导出探测、结果缓存。

登录由 :mod:`westlake_survival.sso` 的 :class:`~westlake_survival.sso.SISAuth`
负责（PeopleSoft 本地登录，成功标志 ``PS_TOKEN`` cookie）。本模块只关心
「登录后怎么把课表拿出来」，两条路线：

1. **HTML 网格**（主路线）：``GET`` 课表页 ``SSR_COMPONENT_FL.GBL``
   （fluid「View My Classes」，网格 ``WL_STDNT_ENR_VW``），交给
   :func:`~westlake_survival.sis.parser.parse_schedule_html`。
2. **xls 导出**（辅路线）：网格头真实存在「Download to Excel」按钮
   （``WL_STDNT_ENR_VW$hexcel$0``），触发**两段式**导出：``POST``
   ``ICAction`` → 响应页含 ``window.open('...ps.xls')`` 下载链接 → ``GET``
   该链接拿到 HTML-in-xls 字节流。找不到导出入口时抛
   :class:`ActionError` 并把关键 HTML 片段放进异常信息。

缓存：:func:`get_schedule` 把结果写入 ``sis/schedule.json``（
:mod:`westlake_survival._cache`），``refresh=True`` 强制刷新。

URL 与参数常量集中在 :data:`SIS_URLS`。

实测校准（2026-09-23 真实登录链路）：

- **课表页**：``SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL?Page=SSR_VW_CLASS_FL``
  （CSPRD_3 portal 即可直达；原假设 ``SSR_MD_SP_FL.GBL`` 对学生角色返回
  "not authorized"）。真实入口链：首页 tile「Semester Enrollment」→
  ``PT_AGSTARTPAGE_NUI.GBL?scname=CS_SSR_MANAGE_CLASSES_NAV`` → 导航集合
  「View Information of Classes」→ 本组件页。
- **页面无学期选择控件**：``STRM`` 参数名假设不成立；页面默认展示当前
  学期的已注册课程（10 门），:meth:`SISClient.fetch_schedule_html` 的
  ``term`` 参数保留但当前不发送任何学期参数。
- **导出按钮**：精确 ``ICAction=WL_STDNT_ENR_VW$hexcel$0``（网格行数
  "10 rows" 旁的下载图标）；导出 POST 的响应是重渲染页面（含
  ``window.open`` 下载链接），真正的 ``ps.xls``（``Content-Type:
  application/vnd.ms-excel``）由第二段 ``GET`` 返回。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

from westlake_survival._cache import load_json, save_json
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.exceptions import (
    ActionError,
    AuthError,
    OffCampusError,
    is_offcampus,
)
from westlake_survival.sis.parser import ClassSession, parse_ps_xls, parse_schedule_html

__all__ = [
    "SIS_URLS",
    "SISClient",
    "get_schedule",
    "fetch_schedule_html",
    "export_schedule_xls",
    "reset_sis",
    "SCHEDULE_CACHE_NAME",
]

logger = logging.getLogger(__name__)

#: 课表结果缓存文件名（相对缓存目录）。
SCHEDULE_CACHE_NAME = "sis/schedule.json"

#: 学生课表「View My Classes」页（fluid 网格 ``WL_STDNT_ENR_VW``）。
#: 2026-09-23 实测：CSPRD_3 portal 直达；未登录 GET 会 302 到 ``?cmd=login``。
SCHEDULE_PAGE = (
    "https://sis.westlake.edu.cn/psc/CSPRD_3/EMPLOYEE/SA/c/"
    "SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL?Page=SSR_VW_CLASS_FL&NavColl=true"
)

#: 真实菜单链入口：首页「Manage Classes」导航集合（Activity Guide 形态）。
#: 从登录后首页 tile「Semester Enrollment」可到达；匿名 GET 302 到登录页。
SCHEDULE_PAGE_MENU = (
    "https://sis.westlake.edu.cn/psp/CSPRD_newwin/EMPLOYEE/SA/c/"
    "NUI_FRAMEWORK.PT_AGSTARTPAGE_NUI.GBL"
    "?CONTEXTIDPARAMS=TEMPLATE_ID%3aPTPPNAVCOL&scname=CS_SSR_MANAGE_CLASSES_NAV"
)

#: PeopleSoft 组件根（导出动作通常打到同 GBL）。
SIS_BASE = "https://sis.westlake.edu.cn/psc/CSPRD_3/"

#: 判定「未登录/会话失效」的 URL 片段。
_CKREQ = "errorPg=ckreq"

#: 导出动作候选模式：PeopleSoft 的 IAction/ICAction 命名。
#: 按优先级排列，命中第一个即返回。动作名可含 ``-``（如
#: ``SSR_SSR-wide_BT_DOWNLOAD$0``）与 ``$``。
_ACTION_CHARS = r"[A-Za-z0-9_$\-]"

#: **精确匹配（2026-09-23 实测）**：fluid 网格导出按钮
#: ``href="javascript:pAction_win17(document.win17,'WL_STDNT_ENR_VW$hexcel$0')"``。
#: 动作 id 必含 ``hexcel``；pAction/submitAction 两种调用形态都认。
_EXPORT_ACTION_PRECISE = re.compile(
    rf"(?:pAction|submitAction)_\w+\(\s*document\.\w+\s*,\s*"
    rf"['\"]({_ACTION_CHARS}*hexcel{_ACTION_CHARS}*)['\"]",
    re.IGNORECASE,
)

_ACTION_PATTERNS = (
    re.compile(rf"ICAction=({_ACTION_CHARS}+)"),
    re.compile(rf"submitAction_{_ACTION_CHARS}+\([^)]*?['\"]({_ACTION_CHARS}+)['\"]"),
    re.compile(rf"({_ACTION_CHARS}*DOWNLOAD{_ACTION_CHARS}*)"),
)

#: **导出下载链接（2026-09-23 实测）**：导出 POST 的响应是重渲染页面，
#: 内含 ``window.open('https://.../view/{V2}.../ps.xls','','')`` 二段式下载。
_EXPORT_URL_RE = re.compile(r"window\.open\(\s*['\"]([^'\"]*ps\.xls[^'\"]*)['\"]")

#: 判定响应体是否就是导出文件本身（而非页面）：``ps.xls`` 为 HTML-in-xls
#: （``<table`` 靠前），而课表页等 PeopleSoft 页面的 ``<table``（网格）在
#: 页面深处、且全文必有 ``ICAction`` 表单域（实测 2026-09-23：真实课表页
#: ``<table`` 在 42KB 处、``ICAction`` 在 6.6KB 处，均不在导出文件的形态里）。
_EXPORT_FILE_MARKERS = (b"<table",)

#: 抓取导出入口时，异常里附带的关键 HTML 片段长度上限。
_SNIPPET_LIMIT = 4000

#: URL 常量集合（2026-09-23 已按真实页面校准；入口链见模块 docstring）。
SIS_URLS: dict[str, str] = {
    "base": SIS_BASE,
    "schedule_page": SCHEDULE_PAGE,
    "schedule_page_menu": SCHEDULE_PAGE_MENU,
    "login": SIS_BASE + "?cmd=login&languageCd=ENG",
}


def _looks_like_login(text: str, url: str = "") -> bool:
    """响应是否是登录页/未登录（ckreq）。

    判定依据（命中任一）：

    - URL 里带 ``cmd=login``（PS 把未登录请求重定向到登录页/错误页）；
    - URL 里带 ``errorPg=ckreq``（未登录被踢）；
    - 正文里出现 PeopleSoft 登录表单特征（``name="userid"`` 与
      ``name="pwd"`` 同时出现，或 ``RespondingWithSignonPage`` 标记）。

    **不**单凭正文出现 ``cmd=login`` 判定：正常页面也可能在退出链接里带它。
    """
    url = url or ""
    if _CKREQ in url:
        return True
    if "cmd=login" in url:
        return True
    low = (text or "")[:8000].lower()
    if 'name="userid"' in low and 'name="pwd"' in low:
        return True
    return False


def _find_export_action(html: str) -> dict[str, str] | None:
    """从课表页 HTML 中找出「导出/下载」动作。

    返回 ``{"ICAction": "...", ...}``（可直接作为 POST 表单字段）；找不到
    返回 ``None``。

    实测确认（2026-09-23）：真实按钮是 fluid 网格头的「Download to Excel」
    图标，``href`` 形如
    ``javascript:pAction_win17(document.win17,'WL_STDNT_ENR_VW$hexcel$0')``。
    因此**精确匹配 ``*hexcel*`` 动作 id 优先**；历史上的启发式模式
    （``ICAction=`` / ``submitAction_*`` / ``*DOWNLOAD*``）保留为兜底，
    以防页面版本变化。
    """
    if not html:
        return None
    precise = _EXPORT_ACTION_PRECISE.search(html)
    if precise and precise.group(1):
        return {"ICAction": precise.group(1)}
    for pattern in _ACTION_PATTERNS:
        match = pattern.search(html)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
            if value:
                return {"ICAction": value}
    # 兜底：直接找带「下载/导出/download」字样的链接附近的 ICAction。
    context_re = re.compile(
        rf"(?:download|导出|下载|excel|export)[\s\S]{{0,300}}?(ICAction=({_ACTION_CHARS}+))",
        re.IGNORECASE,
    )
    match = context_re.search(html)
    if match:
        return {"ICAction": match.group(2)}
    return None


def _find_form_action(html: str) -> str | None:
    """提取课表页主表单的 ``action`` URL（导出 POST 的真实目标）。

    实测（2026-09-23）：PeopleSoft 页面主表单形如
    ``<form id='SSR_COMPONENT_FL' method='post' action='https://.../GBL'>``；
    导出动作应打到该 GBL（不带页面自身的查询参数）。找不到返回 ``None``。
    """
    if not html:
        return None
    match = re.search(
        r"<form\b[^>]*action=[\"']([^\"']+)[\"']", html, re.IGNORECASE
    )
    if not match:
        return None
    return match.group(1).replace("&amp;", "&")


_INPUT_TAG_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_INPUT_NAME_RE = re.compile(r"name=[\"']([^\"']*)[\"']", re.IGNORECASE)
_INPUT_VALUE_RE = re.compile(r"value=[\"']([^\"']*)[\"']", re.IGNORECASE)


def _collect_hidden_fields(html: str) -> dict[str, str]:
    """收集页面主表单的隐藏域（name -> value），作为导出 POST 的表单基座。

    实测（2026-09-23）：导出 POST 需要（或至少接受了）页面自带的
    ``ICStateNum`` / ``ICSID`` 等 26 个隐藏域 + ``ICAction``。单引号/双引号
    属性都认（PeopleSoft 模板渲染为单引号）。
    """
    fields: dict[str, str] = {}
    for tag in _INPUT_TAG_RE.findall(html or ""):
        if not re.search(r"type=[\"']hidden[\"']", tag, re.IGNORECASE):
            continue
        name = _INPUT_NAME_RE.search(tag)
        if not name:
            continue
        value = _INPUT_VALUE_RE.search(tag)
        fields[name.group(1)] = value.group(1) if value else ""
    return fields


def _find_export_url(html: str) -> str | None:
    """从导出 POST 的响应页中提取 ``window.open('...ps.xls')`` 下载链接。

    实测确认（2026-09-23）：导出 POST 的响应是重渲染的课表页（不是文件），
    其中内嵌 ``window.open('https://.../view/{V2}.../ps.xls','','')``，由
    浏览器打开该链接完成下载。找到返回链接，否则 ``None``。
    """
    if not html:
        return None
    match = _EXPORT_URL_RE.search(html)
    if not match:
        return None
    return match.group(1).replace("&amp;", "&")


def _looks_like_export_file(headers: Any, content: bytes) -> bool:
    """判定响应是否就是导出文件本身（而非 PeopleSoft 页面）。

    依次看：响应头 ``Content-Type`` 含 ``excel``（实测为
    ``application/vnd.ms-excel``）／``Content-Disposition`` 含 ``.xls``；
    兜底看正文——``ps.xls`` 是 HTML-in-xls（``<table`` 在文件头部），而
    PeopleSoft 页面的 ``<table>``（fluid 网格）在页面深处、且**全文**必含
    ``ICAction`` 表单域（故对全文而非仅前 4KB 检查）。
    """
    if not content:
        return False
    content_type = str(getattr(headers, "get", lambda *_: "")("Content-Type", "") or "")
    disposition = str(
        getattr(headers, "get", lambda *_: "")("Content-Disposition", "") or ""
    )
    if "excel" in content_type.lower() or ".xls" in disposition.lower():
        return True
    return (
        any(marker in content[:4096] for marker in _EXPORT_FILE_MARKERS)
        and b"ICAction" not in content
    )


class SISClient:
    """SIS 教务客户端。

    Args:
        auth: 可注入的 :class:`~westlake_survival.sso.SISAuth`（测试用）；
            ``None`` 时惰性取 :class:`SISAuth` 单例。
        session: 已登录的 :class:`requests.Session`（测试用）；提供后不再走
            ``auth`` 的自动登录，直接用它发请求。
    """

    def __init__(self, auth: Any = None, session: requests.Session | None = None) -> None:
        self._auth = auth
        self._session = session

    # ------------------------------------------------------------ 内部

    def _get_session(self) -> requests.Session:
        """返回已确保登录的 Session。"""
        if self._session is not None:
            return self._session
        if self._auth is None:
            from westlake_survival.sso import SISAuth

            self._auth = SISAuth()
        return self._auth.session

    def _get(self, url: str, **kw: Any) -> requests.Response:
        """发 GET 请求；统一超时。"""
        session = self._get_session()
        kw.setdefault("timeout", DEFAULT_TIMEOUT)
        kw.setdefault("allow_redirects", True)
        return session.get(url, **kw)

    def _post(self, url: str, **kw: Any) -> requests.Response:
        session = self._get_session()
        kw.setdefault("timeout", DEFAULT_TIMEOUT)
        kw.setdefault("allow_redirects", True)
        return session.post(url, **kw)

    def _guard_response(self, response: requests.Response) -> None:
        """把登录页/校外阻断响应映射为异常。"""
        if is_offcampus(response):
            raise OffCampusError(
                "SIS 仅校园网/VPN 内可达，请先连接西湖大学 VPN 后重试。"
            )
        url = getattr(response, "url", "") or ""
        text = getattr(response, "text", "") or ""
        if _looks_like_login(text, url):
            raise AuthError(
                "SIS 会话未登录或已失效（响应为登录页/ckreq）。"
                "请确认凭据有效并已连接校园网。"
            )

    # -------------------------------------------------------- 公开 API

    def fetch_schedule_html(self, term: str | None = None) -> str:
        """抓取课表页 HTML。

        Args:
            term: 学期标识。**2026-09-23 实测：真实课表页（fluid
                ``SSR_COMPONENT_FL``「View My Classes」）没有学期选择控件**，
                原先假设的 ``STRM`` 查询参数名不成立，页面固定展示当前学期
                的已注册课程；因此 *term* 目前仅保留作 API 兼容，**不会**
                附加任何查询参数。

        Returns:
            课表页 HTML 文本。

        Raises:
            AuthError: 响应是登录页（未登录/会话失效）。
            OffCampusError: 校外访问被拒。
        """
        response = self._get(SIS_URLS["schedule_page"])
        self._guard_response(response)
        return response.text or ""

    def export_schedule_xls(self, term: str | None = None) -> bytes:
        """触发 SIS 网格的「Download to Excel」动作，返回 ``ps.xls`` 字节。

        实测流程（2026-09-23，两段式）：

        1. 登录态 ``GET`` 课表页，从 HTML 中找导出动作
           （:func:`_find_export_action`，精确 ``*hexcel*`` 优先）；
        2. 对课表页主表单的 ``action`` GBL ``POST`` 页面全部隐藏域 +
           ``ICAction``（实测 2026-09-23：26 个隐藏域 + 动作 id）——响应是
           重渲染页面而非文件；
        3. 从响应页提取 ``window.open('...ps.xls')`` 下载链接
           （:func:`_find_export_url`），``GET`` 该链接拿到真正的导出文件
           （``Content-Type: application/vnd.ms-excel``，HTML-in-xls）。

        若响应直接就是文件（老式行为兜底），则原样返回。找不到导出入口
        或下载链接时抛 :class:`ActionError`，并把关键 HTML 片段放入异常信息。

        Args:
            term: 学期标识，见 :meth:`fetch_schedule_html`（当前不发送）。

        Returns:
            导出文件字节（HTML-in-xls）。

        Raises:
            ActionError: 页面上找不到导出入口或下载链接。
            AuthError / OffCampusError: 见 :meth:`fetch_schedule_html`。
        """
        html = self.fetch_schedule_html(term=term)
        action = _find_export_action(html)
        if not action:
            snippet = _snippet(html)
            raise ActionError(
                "未找到导出入口，请反馈课表页 HTML。"
                "（SIS 的下载按钮在未登录页面不可见，需要你登录后提供该页 HTML "
                "以校准 _find_export_action 的匹配模式。）\n"
                f"页面片段：{snippet}"
            )
        post_url = _find_form_action(html) or SIS_URLS["schedule_page"]
        data = _collect_hidden_fields(html)
        data["ICAction"] = action["ICAction"]
        response = self._post(post_url, data=data)
        self._guard_response(response)
        content = response.content or b""
        if not content:
            raise ActionError(f"导出动作 {action} 返回空内容，请反馈课表页 HTML。")
        # 第一段：POST 响应可能直接就是文件（兜底），或重渲染页面（实测）。
        if _looks_like_export_file(response.headers, content):
            return content
        # 第二段：从重渲染页面提取 window.open('...ps.xls') 下载链接。
        download_url = _find_export_url(response.text or "")
        if not download_url:
            raise ActionError(
                f"导出动作 {action} 的响应中未找到 ps.xls 下载链接，"
                "请反馈课表页 HTML 以校准。\n"
                f"响应片段：{_snippet(response.text or '')}"
            )
        download = self._get(download_url)
        self._guard_response(download)
        body = download.content or b""
        if not body:
            raise ActionError("导出下载链接返回空内容，请反馈课表页 HTML。")
        return body

    def get_schedule(
        self, *, refresh: bool = False, source: str = "html"
    ) -> list[ClassSession]:
        """取课表节次列表，带缓存。

        Args:
            refresh: 为 ``True`` 时跳过缓存，强制重新抓取。
            source: ``"html"``（默认，解析课表页网格）或 ``"xls"``（走导出）。

        Returns:
            :class:`ClassSession` 列表。

        Raises:
            ValueError: *source* 不是 ``"html"`` / ``"xls"``。
        """
        if source not in ("html", "xls"):
            raise ValueError(f"未知 source：{source!r}（应为 'html' 或 'xls'）")

        if not refresh:
            cached = load_json(SCHEDULE_CACHE_NAME)
            if isinstance(cached, list):
                return [ClassSession.from_dict(item) for item in cached]

        if source == "xls":
            sessions = parse_ps_xls(self.export_schedule_xls())
        else:
            sessions = parse_schedule_html(self.fetch_schedule_html())

        save_json(SCHEDULE_CACHE_NAME, [s.to_dict() for s in sessions])
        return sessions


def _snippet(html: str) -> str:
    """截取 HTML 关键片段（供异常信息展示）。"""
    if not html:
        return "<空响应>"
    # 优先截取疑似网格/表格区域。
    for marker in ("<table", "id=\"ACE_", "WL_STDNT_ENR_VW", "SSR_MD_SP_FL"):
        index = html.find(marker)
        if index >= 0:
            return html[index : index + _SNIPPET_LIMIT]
    return html[:_SNIPPET_LIMIT]


# --------------------------------------------------------------------------- #
# 模块级单例与便捷函数
# --------------------------------------------------------------------------- #
_singleton: SISClient | None = None


def _client() -> SISClient:
    global _singleton
    if _singleton is None:
        _singleton = SISClient()
    return _singleton


def reset_sis() -> None:
    """清空模块级客户端单例（测试用）。"""
    global _singleton
    _singleton = None


def fetch_schedule_html(term: str | None = None) -> str:
    """便捷函数：用单例客户端抓取课表页 HTML。"""
    return _client().fetch_schedule_html(term=term)


def export_schedule_xls(term: str | None = None) -> bytes:
    """便捷函数：用单例客户端尝试导出 ``ps.xls``。"""
    return _client().export_schedule_xls(term=term)


def get_schedule(
    *, refresh: bool = False, source: str = "html"
) -> list[ClassSession]:
    """便捷函数：用单例客户端取课表节次列表（带缓存）。"""
    return _client().get_schedule(refresh=refresh, source=source)