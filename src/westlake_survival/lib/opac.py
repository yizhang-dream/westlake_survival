"""图书馆检索：OPAC（阿法迪 JSP 老系统）与资源门户（bookreport JSON API）。

实测结论（2026-09-22，详见模块文档与仓库报告）：

- ``opac.westlake.edu.cn`` 是 **静态镜像**：首页 200，但 ``/opac/booklist.jsp``
  等真实检索路径由 nginx 直接 404；真正的 OPAC 应用上下文 ``/opac`` 已不在
  线（内部主机 ``172.16.10.223:8180`` 上该上下文同样 404）。站点首页自带的
  检索表单 action 指向 ``http://172.16.10.223:8180/opac/booklist.jsp``，本模块
  即以该端点作为公开检索的规范端点（可通过 ``WESTLAKE_OPAC_BASE`` 覆盖）。
- ``catalog.lib.westlake.edu.cn``（bookreport，Vue SPA）后端 JSON API 位于
  ``/headless/bolan-*/api/...``，**匿名访问一律 401（需要先登录）**；仅有
  ``POST /bolan-newbook/api/newbook/tenantRule`` 匿名可用。因此 JSON 路线需
  带认证会话（:class:`westlake_survival.sso.LibAuth`）。

公开（无鉴权）检索走 HTML 路线；带认证会话时可改走 JSON 路线。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.exceptions import (
    AuthError,
    OffCampusError,
    ParseError,
    WestlakeError,
    is_offcampus,
)
from westlake_survival.lib.models import Book, Loan

# --------------------------------------------------------------------------- #
# 端点常量（实测）
# --------------------------------------------------------------------------- #

#: OPAC 应用基址。默认取站点检索表单 action 所指的真实端点；可用环境变量覆盖。
OPAC_BASE = os.environ.get("WESTLAKE_OPAC_BASE", "http://172.16.10.223:8180/opac")

#: 资源/新书门户（bookreport SPA）。
CATALOG_BASE = os.environ.get("WESTLAKE_CATALOG_BASE", "https://catalog.lib.westlake.edu.cn")

#: 门户 JSON 网关前缀：前端 axios 拦截器给 ``/api``、``/admin`` 开头的 URL 自动加 ``/headless``。
CATALOG_API = CATALOG_BASE + "/headless"

#: 公开书目检索（表单 POST）。
SEARCH_PATH = "/booklist.jsp"

#: 新书推荐列表（站点菜单 ``newbooklist.jsp?target=2``）。
NEW_BOOKS_PATH = "/newbooklist.jsp"

#: 检索类型 -> OPAC ``searchtype`` 取值（站点下拉框实测）。
_KIND_MAP = {
    "keyword": "keyword",
    "any": "keyword",
    "title": "title",
    "author": "author",
    "isbn": "isbn",
    "issn": "isbn",
    "subject": "subject",
    "seriesname": "seriesname",
    "classno": "classno",
    "callno": "callno",
    "call_no": "callno",
    "publisher": "publish",
    "publish": "publish",
    "publishdate": "publishdate",
    "year": "publishdate",
    "content": "content",
}

#: 个人借阅页候选路径（阿法迪常见读者页；实测当前 OPAC 上下文离线，
#: 路径常量列表待有账号后在真实读者端点上校准）。
READER_LOAN_PATHS: tuple[str, ...] = (
    "/reader/loanList.do",
    "/reader/myLoan.do",
    "/reader/myLoanList.do",
    "/reader/loanList.jsp",
    "/reader/myLoan.jsp",
    "/reader/bookLoanList.do",
    "/page/reader/loanList.do",
    "/page/reader/myLoan.jsp",
)

#: 字段标签（中/英）-> Book 字段；用于在无固定 DOM 结构时按文本抽取。
_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "author": ("作者", "责任者", "著者", "Author"),
    "publisher": ("出版社", "出版者", "出版发行", "Publisher"),
    "publish_year": ("出版年", "出版日期", "出版时间", "Year"),
    "call_no": ("索书号", "Call No", "CallNo"),
    "isbn": ("ISBN", "ISSN", "isbn"),
    "location": ("馆藏地", "馆藏地点", "馆藏", "分馆", "所在地", "Location"),
}

_GENERIC_ENCODINGS = ("iso-8859-1", "latin-1", "ascii", "")

#: 全部字段标签（长标签优先），用于在无分隔符的文本里界定值的边界。
_ALL_LABELS = tuple(
    sorted({label for labels in _FIELD_LABELS.values() for label in labels}, key=len, reverse=True)
)


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #


def _session():
    """创建默认 HTTP 会话（测试可注入自定义 session）。"""
    return http_session()


def _decode_html(response: Any) -> str:
    """把响应体解码为文本，兼容老 JSP 的 GBK/GB2312。

    优先级：HTML ``meta charset`` > Content-Type 头 > ``apparent_encoding`` > utf-8。
    """
    raw = getattr(response, "content", None)
    if raw is None:  # 兜底：只有 text
        return getattr(response, "text", "") or ""
    match = re.search(rb"""charset=["']?\s*([\w-]+)""", raw[:4096], re.I)
    encoding = ""
    if match:
        encoding = match.group(1).decode("ascii", "ignore")
    if not encoding:
        header_enc = (getattr(response, "encoding", "") or "")
        if header_enc.lower() not in _GENERIC_ENCODINGS:
            encoding = header_enc
    if not encoding:
        encoding = getattr(response, "apparent_encoding", None) or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _check_response(response: Any) -> None:
    """把 HTTP 层失败翻译成库内异常。"""
    status = getattr(response, "status_code", 200)
    if status == 403:
        if is_offcampus(response):
            raise OffCampusError("图书馆系统拒绝访问：仅校园网/VPN 内可达")
        raise OffCampusError(f"图书馆系统返回 403（可能需校园网或登录）：{_url_of(response)}")
    if status == 401:
        raise AuthError("图书馆接口要求登录（401）")
    if status >= 400:
        raise ParseError(f"图书馆接口返回 HTTP {status}：{_url_of(response)}")


def _url_of(response: Any) -> str:
    return getattr(response, "url", "") or ""


def _json(response: Any) -> Any:
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError) as exc:  # pragma: no cover - 防御
        raise ParseError("接口未返回合法 JSON") from exc


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _abs_url(href: str, base: str) -> str:
    if not href:
        return ""
    return urljoin(base if base.endswith("/") else base + "/", href)


# --------------------------------------------------------------------------- #
# HTML 解析：检索列表
# --------------------------------------------------------------------------- #


def _extract_labeled(text: str, labels: Iterable[str]) -> str:
    """从一段文本里按"标签：值"抽取字段值。

    值以"下一个字段标签"或分隔符为界，避免吞掉后续著录项。
    """
    for label in labels:
        pattern = re.compile(re.escape(label) + r"\s*[:：]?\s*([^;；|｜\n]{1,80})", re.I)
        match = pattern.search(text)
        if not match:
            continue
        value = match.group(1)
        cut = len(value)
        for other in _ALL_LABELS:
            # 只在"标签紧跟冒号"处截断，避免把值里同名的词（如"清华大学出版社"）误当下一字段
            boundary = re.search(re.escape(other) + r"\s*[:：]", value)
            if boundary is not None and 0 < boundary.start() < cut:
                cut = boundary.start()
        value = _clean(value[:cut])
        if value:
            return value
    return ""


def _book_from_node(node: Any, base_url: str) -> Book | None:
    """从一个书目节点（div/li/tr）抽取 :class:`Book`。"""
    # 题名与详情链接
    title = ""
    detail_url = ""
    title_node = node.select_one(
        ".book-fld-title, .bookfld-title, .book-name, .title, "
        "a[href*=bookdetail], a[href*=bookDetail]"
    )
    if title_node is not None:
        title = _clean(title_node.get_text(" ", strip=True))
        anchor = title_node if title_node.name == "a" else title_node.find("a")
        if anchor is not None and anchor.get("href"):
            detail_url = _abs_url(anchor["href"], base_url)
    if not detail_url:
        anchor = node.find("a", href=True)
        if anchor is not None and re.search(r"bookdetail|bookDetail|bibDetail", anchor["href"]):
            detail_url = _abs_url(anchor["href"], base_url)

    # 其余字段：优先从 .book-fld-other 文本抽，退化到整块文本
    other_node = node.select_one(".book-fld-other, .bookfld-other, .book-fld, .info, .fld")
    if other_node is not None:
        text = other_node.get_text(" ", strip=True)
    else:
        text = node.get_text(" ", strip=True)

    book = Book(
        title=title,
        author=_extract_labeled(text, _FIELD_LABELS["author"]),
        publisher=_extract_labeled(text, _FIELD_LABELS["publisher"]),
        publish_year=_extract_labeled(text, _FIELD_LABELS["publish_year"]),
        call_no=_extract_labeled(text, _FIELD_LABELS["call_no"]),
        isbn=_extract_labeled(text, _FIELD_LABELS["isbn"]),
        location=_extract_labeled(text, _FIELD_LABELS["location"]),
        detail_url=detail_url,
    )
    if not (book.title or book.author or book.isbn or book.call_no):
        return None
    return book


def parse_book_list(html: str, base_url: str = OPAC_BASE) -> list[Book]:
    """解析 OPAC 检索结果 HTML 为 :class:`Book` 列表（容错，多种布局）。"""
    soup = BeautifulSoup(html, "html.parser")
    books: list[Book] = []

    selectors = (
        "div.book-list",
        "li.book-list",
        "tr.book-list",
        ".booklist-box .book-list",
        "table.booktable tr",
    )
    for selector in selectors:
        for node in soup.select(selector):
            book = _book_from_node(node, base_url)
            if book is not None:
                books.append(book)
        if books:
            break

    if not books:
        # 退化：任何含详情链接的容器
        for node in soup.find_all("div"):
            if node.find("a", href=re.compile(r"bookdetail|bookDetail", re.I)):
                book = _book_from_node(node, base_url)
                if book is not None:
                    books.append(book)

    return books


# --------------------------------------------------------------------------- #
# HTML 解析：详情页 / 借阅页
# --------------------------------------------------------------------------- #


def parse_book_detail(html: str, book: Book | None = None) -> Book:
    """解析书目详情页，补全馆藏地与在馆状态。

    在检索列表（仅摘要）基础上，详情页给出各分馆的馆藏行；此处汇总为
    ``location``/``holding_status`` 两个字段。
    """
    soup = BeautifulSoup(html, "html.parser")
    result = Book(**book.to_dict()) if book is not None else Book()

    if not result.title:
        title_node = soup.select_one(".detail-title, h1, h2, .book-title")
        if title_node is not None:
            result.title = _clean(title_node.get_text(" ", strip=True))

    text = soup.get_text(" ", strip=True)
    if not result.isbn:
        result.isbn = _extract_labeled(text, _FIELD_LABELS["isbn"])
    if not result.author:
        result.author = _extract_labeled(text, _FIELD_LABELS["author"])
    if not result.call_no:
        result.call_no = _extract_labeled(text, _FIELD_LABELS["call_no"])

    locations: list[str] = []
    statuses: list[str] = []
    for row in soup.select("tr, li.hld-item, .hld-list .item, .hold-item"):
        cells = [_clean(td.get_text(" ", strip=True)) for td in row.find_all("td")]
        if not cells:
            continue
        joined = " ".join(cells)
        if re.search(r"在馆|可借|借出|馆藏|收藏", joined):
            for cell in cells:
                if re.search(r"馆|校区|书库|阅览|分馆", cell):
                    locations.append(cell)
                if re.search(r"在馆|可借|借出|归还|预约|不外借|不外", cell):
                    statuses.append(cell)
    if locations:
        result.location = locations[0]
    if statuses:
        available = [s for s in statuses if re.search(r"在馆|可借", s)]
        result.holding_status = available[0] if available else statuses[0]
    return result


def parse_loans(html: str) -> list[Loan]:
    """解析读者借阅页 HTML 为 :class:`Loan` 列表。

    以表头文字定位列（题名/条码号/应还日期/续借/馆藏地），对列顺序与
    分馆差异免疫。
    """
    soup = BeautifulSoup(html, "html.parser")
    loans: list[Loan] = []

    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all("td") if first_row else []
        headers = [_clean(c.get_text(" ", strip=True)) for c in header_cells]
        if not headers:
            continue
        header_line = " ".join(headers)
        if not re.search(r"题名|书名|条码|应还|归还|借阅|续借", header_line):
            continue

        def col(*keywords: str) -> int | None:
            for index, name in enumerate(headers):
                if any(k in name for k in keywords):
                    return index
            return None

        idx_title = col("题名", "书名", "著者", "文献")
        idx_barcode = col("条码")
        idx_due = col("应还", "归还日期", "到期")
        idx_renew = col("续借", "可续")
        idx_loc = col("馆藏地", "馆藏地点", "所在地", "分馆", "馆藏")

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            values = [_clean(c.get_text(" ", strip=True)) for c in cells]

            def at(index: int | None) -> str:
                if index is None or index >= len(values):
                    return ""
                return values[index]

            title = at(idx_title)
            barcode = at(idx_barcode)
            due = at(idx_due)
            if not (title or barcode or due):
                continue
            loans.append(
                Loan(
                    title=title,
                    barcode=barcode,
                    due_date=due,
                    renewable=_parse_renewable(at(idx_renew)),
                    location=at(idx_loc),
                )
            )
        if loans:
            break
    return loans


def _parse_renewable(value: str) -> bool | None:
    if not value:
        return None
    if re.search(r"不可|不能|否|no", value, re.I):
        return False
    if re.search(r"可|是|yes", value, re.I):
        return True
    return None


# --------------------------------------------------------------------------- #
# JSON 解析：bookreport 门户
# --------------------------------------------------------------------------- #


def _catalog_payload_items(payload: Any) -> list[dict[str, Any]]:
    """从门户 JSON 信封中取出条目列表。"""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("success") is False or payload.get("code") == "UNAUTHORIZED":
        raise AuthError(payload.get("message") or "门户接口要求登录")
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("list", "records", "rows", "items", "content", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def parse_catalog_books(payload: Any, base_url: str = CATALOG_BASE) -> list[Book]:
    """解析门户 JSON 检索结果为 :class:`Book` 列表（字段名容错）。"""
    books: list[Book] = []
    for item in _catalog_payload_items(payload):

        def pick(*keys: str) -> str:
            for key in keys:
                if item.get(key) not in (None, ""):
                    return _clean(item[key])
            return ""

        book_id = pick("id", "bookid", "bookId", "bibId")
        detail_url = ""
        if book_id:
            detail_url = f"{base_url.rstrip('/')}/bookdetail?id={book_id}"
        books.append(
            Book(
                title=pick("title", "bookname", "bookName", "name"),
                author=pick("author", "authors", "responsible"),
                publisher=pick("publisher", "press", "pubhouse"),
                publish_year=pick("publishdate", "publishYear", "publishyear", "year"),
                call_no=pick("callnumber", "callno", "callNo"),
                isbn=pick("isbn", "issn"),
                location=pick("location", "libname", "library", "collection"),
                holding_status=pick("status", "holdstatus", "holdingStatus"),
                detail_url=detail_url,
            )
        )
    return books


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #


def search(
    keyword: str,
    *,
    page: int = 1,
    kind: str = "title",
    session: Any = None,
    source: str = "opac",
) -> list[Book]:
    """检索书目。

    Args:
        keyword: 检索词。
        page: 页码（从 1 开始）。
        kind: 检索类型，见 :data:`_KIND_MAP`（``title``/``author``/``isbn``/``keyword``…）。
        session: 可选注入的 :class:`requests.Session`（测试用）。
        source: ``"opac"``（默认，公开 HTML 路线）或 ``"catalog"``（门户 JSON，需登录会话）。

    Returns:
        :class:`Book` 列表；无结果时为空列表。

    Raises:
        ParseError: 端点不可达或页面结构无法解析。
        OffCampusError: 被校外访问网关拦截（403）。
        AuthError: JSON 路线会话未登录（401）。
    """
    if source == "catalog":
        return _search_catalog(keyword, page=page, kind=kind, session=session)

    session = session or _session()
    searchtype = _KIND_MAP.get(kind, kind)
    response = session.post(
        OPAC_BASE + SEARCH_PATH,
        data={
            "searchtype": searchtype,
            "searchkey": keyword,
            "libcode": "",
            "page": str(page),
            "curpage": str(page),
        },
        timeout=DEFAULT_TIMEOUT,
    )
    _check_response(response)
    html = _decode_html(response)
    books = parse_book_list(html, OPAC_BASE)
    if not books and not _looks_like_result_page(html):
        raise ParseError(
            f"OPAC 检索端点返回的页面无法解析（{OPAC_BASE + SEARCH_PATH}）；"
            "实测该端点当前可能已下线，详见模块文档"
        )
    return books


def search_catalog(
    keyword: str,
    *,
    page: int = 1,
    kind: str = "title",
    session: Any = None,
) -> list[Book]:
    """门户 JSON 检索（需已登录会话；见 :class:`westlake_survival.sso.LibAuth`）。"""
    return _search_catalog(keyword, page=page, kind=kind, session=session)


def _search_catalog(keyword: str, *, page: int, kind: str, session: Any) -> list[Book]:
    session = session or _session()
    payload = {
        "indexname": "newbook_batchbook",
        "newsearh": keyword,
        "searchtype": _KIND_MAP.get(kind, kind),
        "curpage": page,
        "pagesize": 20,
    }
    response = session.post(
        CATALOG_API + "/bolan-newbook/api/newbook/search/",
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    _check_response(response)
    return parse_catalog_books(_json(response), CATALOG_BASE)


def book_detail(book: Book, *, session: Any = None) -> Book:
    """补全书目详情（馆藏地/在馆状态）。

    无 ``detail_url`` 时原样返回。
    """
    if not book.detail_url:
        return book
    session = session or _session()
    response = session.get(book.detail_url, timeout=DEFAULT_TIMEOUT)
    _check_response(response)
    return parse_book_detail(_decode_html(response), book)


def new_books(limit: int = 20, *, session: Any = None, source: str = "opac") -> list[Book]:
    """新书推荐列表。

    Args:
        limit: 最多返回条数。
        session: 可选注入会话。
        source: ``"opac"``（默认，站点新书页）或 ``"catalog"``（门户 JSON，需登录）。
    """
    if source == "catalog":
        return _new_books_catalog(limit=limit, session=session)
    session = session or _session()
    response = session.get(
        OPAC_BASE + NEW_BOOKS_PATH,
        params={"target": 2},
        timeout=DEFAULT_TIMEOUT,
    )
    _check_response(response)
    books = parse_book_list(_decode_html(response), OPAC_BASE)
    return books[:limit]


def _new_books_catalog(*, limit: int, session: Any) -> list[Book]:
    session = session or _session()
    payload = {
        "indexname": "newbook_batchbook",
        "newsearh": "",
        "searchtype": "keyword",
        "curpage": 1,
        "pagesize": max(1, limit),
    }
    response = session.post(
        CATALOG_API + "/bolan-newbook/api/newbook/search/",
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    _check_response(response)
    return parse_catalog_books(_json(response), CATALOG_BASE)[:limit]


def my_loans(*, auth: Any = None, session: Any = None) -> list[Loan]:
    """当前借阅记录（需登录）。

    使用 :class:`westlake_survival.sso.LibAuth` 单例的已认证会话，遍历
    :data:`READER_LOAN_PATHS` 候选路径，命中第一个可解析的读者页。

    Raises:
        AuthError: 会话未登录（命中登录页）。
        ParseError: 所有候选路径均不可达/不可解析（当前 OPAC 上下文离线，
            需有账号后在真实读者端点上校准 :data:`READER_LOAN_PATHS`）。
    """
    auth = auth if auth is not None else _lib_auth()
    get = auth.get if hasattr(auth, "get") else (session or _session()).get

    last_status = None
    for path in READER_LOAN_PATHS:
        url = OPAC_BASE + path
        try:
            response = get(url)
        except WestlakeError:
            raise
        if response is None:
            continue
        status = getattr(response, "status_code", 200)
        if status == 403:
            _check_response(response)  # 抛 OffCampusError/AuthError
        if status >= 400:
            last_status = status
            continue
        html = _decode_html(response)
        if _looks_like_login_page(html):
            raise AuthError("借阅页跳转到登录页，会话未认证")
        loans = parse_loans(html)
        if loans or _looks_like_loan_page(html):
            return loans
    raise ParseError(
        "未能定位个人借阅页（候选路径均不可达："
        f"{', '.join(READER_LOAN_PATHS)}；最近 HTTP {last_status}）"
    )


def _lib_auth() -> Any:
    """延迟获取 sso 认证单例；并行模块未就绪时给出清晰错误。"""
    try:
        from westlake_survival.sso import LibAuth  # noqa: WPS433 (延迟导入)
    except Exception as exc:  # pragma: no cover - 依赖并行任务
        raise WestlakeError(
            "westlake_survival.sso.LibAuth 不可用（SSO 模块未实现或导入失败）；"
            "个人借阅需先完成 SSO 登录"
        ) from exc
    return LibAuth()


# --------------------------------------------------------------------------- #
# 页面特征判断
# --------------------------------------------------------------------------- #


def _looks_like_result_page(html: str) -> bool:
    if not html:
        return False
    return bool(re.search(r"检索结果|共\s*\d+\s*条|book-list|booktable|search-list", html))


#: 密码输入框（老 JSP 偶见裸 ``<input>`` 不带 ``<form>``，故单列一条正则兜底）。
_PASSWORD_INPUT_RE = re.compile(r"<input[^>]*\btype\s*=\s*[\"']?\s*password\b", re.I)

#: 读者页特征（借阅列表/续借入口）。出现且无密码输入框时优先判为非登录页。
_READER_HINT_RE = re.compile(r"借阅|在借|续借|应还|归还|条码号")

#: 改密/找回密码入口：普通读者页常见“修改密码 password”链接，不等于登录表单。
_CHANGE_PASSWORD_HINT_RE = re.compile(
    r"修改密码|更改密码|重置密码|忘记密码|change\s*password|forgot\s*password",
    re.I,
)


def _has_password_input(html: str) -> bool:
    """HTML 中是否存在承载密码输入的登录表单。

    优先用 bs4 做“``<form>`` 内含 ``type=password`` 输入”的结构化检测；
    页面完全没有 ``<form>`` 时（老 JSP 裸 input 提交）退回正则匹配。
    """
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form")
    if not forms:
        return bool(_PASSWORD_INPUT_RE.search(html))
    for form in forms:
        for node in form.find_all("input"):
            if (node.get("type") or "").strip().lower() == "password":
                return True
    return False


def _looks_like_login_page(html: str) -> bool:
    """判断响应体是否为登录页（用于 ``my_loans`` 抛 :class:`AuthError`）。

    判定顺序（防御性收紧，不再依赖“password + login 子串共现”）：

    1. 命中“``<form>`` 内含密码输入框”即判 True——这是登录表单的结构特征，
       纯中文登录页（按钮写“提交”而非“登录”）也能覆盖；
    2. 正文出现读者页特征（借阅/在借/续借/应还/归还/条码号）且无密码输入框
       时判 False，避免读者页上“登录”导航词被误判；
    3. 正文出现改密/找回密码入口（“修改密码 password”之类链接）且无密码
       输入框时判 False；
    4. 兜底保留旧的子串共现规则（``password|passwd`` 与 ``login|登录`` 同时
       出现）。**局限**：无表单且无上述排除词的静态页仍可能误判——待
       ``:8180/opac`` 上下文恢复后，用真实读者页/登录页校准并替换本条兜底。
    """
    if not html:
        return False
    if _has_password_input(html):
        return True
    if _READER_HINT_RE.search(html):
        return False
    if _CHANGE_PASSWORD_HINT_RE.search(html):
        return False
    lower = html.lower()
    return ("password" in lower or "passwd" in lower) and ("login" in lower or "登录" in html)


def _looks_like_loan_page(html: str) -> bool:
    return bool(re.search(r"借阅|应还|归还|续借|条码号", html or ""))


__all__ = [
    "Book",
    "Loan",
    "search",
    "search_catalog",
    "book_detail",
    "new_books",
    "my_loans",
    "parse_book_list",
    "parse_book_detail",
    "parse_loans",
    "parse_catalog_books",
    "OPAC_BASE",
    "CATALOG_BASE",
    "READER_LOAN_PATHS",
]