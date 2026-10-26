"""SIS 通用页面读取层：登录态抓页 + fluid 网格 / label-value 解析。

:mod:`westlake_survival.sis.client` 把「课表」这一条线做成了带缓存的完整
客户端；成绩、考试等其余组件页彼此同构——都是登录态下 ``GET`` 一个
PeopleSoft 组件 URL，再从 fluid 网格或 label-value 区块里取字段。本模块把
这两件事抽成可复用的最小原语：

- :func:`fetch_page`：登录态 ``GET`` 任意 SIS 组件页，返回 HTML；
- :func:`parse_fluid_grid`：按网格 id 定位 fluid 表格，用表头 ``th`` 文本做键
  抽行数据；
- :func:`parse_label_values`：解析 ``ps_box-label`` / ``ps_box-value`` 键值对
  （个人信息 / 学籍页等后续使用）。

URL 与门户索引（关键坑位）
==========================
SIS 路径形如 ``https://sis.westlake.edu.cn/psc/{CSPRD_x}/EMPLOYEE/SA/c/{组件}``，
其中 ``x`` 是**会话态门户索引**：随登录会话在 ``CSPRD_3`` … ``CSPRD_21`` 之间
变化，**不能写死**。:func:`fetch_page` 每次先从官网根地址的响应最终 URL
（``final_url`` / ``url``）里解析出当前 ``CSPRD_x``，再拼组件页地址。

异常映射
========
:func:`fetch_page` 把三类非正常响应翻译成库内异常：

- 校外阻断 → :class:`~westlake_survival.exceptions.OffCampusError`；
- 登录页 / 会话失效（``cmd=login`` / ``ckreq`` / 登录表单）→
  :class:`~westlake_survival.exceptions.AuthError`；
- 组件页拒答「**not authorized**」→
  :class:`~westlake_survival.exceptions.ActionError`（认证已通过、但该组件对
  当前角色未授权，属「业务动作被拒绝」而非登录失败）。

解析风格
========
网格解析复用 :mod:`westlake_survival.sis.parser` 的容错表格解析器
（:class:`~westlake_survival.sis.parser._TolerantTableParser`）：``<br />``
记为换行，单元格内多值以 ``\\n`` 分隔；本模块在此之上按 ``grid_id`` 先切出
目标 ``<table>``，避免一页多表格互相串行。
"""

from __future__ import annotations

import dataclasses
import re
from html.parser import HTMLParser

from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.exceptions import (
    ActionError,
    AuthError,
    OffCampusError,
    ParseError,
    is_offcampus,
)
from westlake_survival.sis.client import _looks_like_login
from westlake_survival.sis.parser import _parse_tables

__all__ = [
    "SIS_HOST",
    "DEFAULT_PORTAL",
    "COMPONENT_URL_TEMPLATE",
    "fetch_page",
    "form_state",
    "parse_fluid_grid",
    "parse_label_values",
    "named_fields_empty",
    "assert_named_fields",
]

#: SIS 主机根地址（无门户索引）。
SIS_HOST = "https://sis.westlake.edu.cn"

#: 默认（也是实测最常见的）门户索引；仅作解析失败时的兜底。
DEFAULT_PORTAL = "CSPRD_3"

#: 组件页 URL 模板：``{}`` 依次为门户索引与组件名。
COMPONENT_URL_TEMPLATE = SIS_HOST + "/psc/{portal}/EMPLOYEE/SA/c/{component}"

#: 从任意 SIS URL 中提取门户索引 ``CSPRD_x``。
_PORTAL_RE = re.compile(r"/psc/(CSPRD_\d+)/")

#: 门户根地址模板（用于探测当前会话的门户索引）。
_PORTAL_ROOT_TEMPLATE = SIS_HOST + "/psc/{portal}/"

#: 未授权组件页的正文特征（PeopleSoft 对无权限角色返回的提示）。
_NOT_AUTHORIZED = "not authorized"


# --------------------------------------------------------------------------- #
# 网络：登录态 GET
# --------------------------------------------------------------------------- #
def _session():
    """返回已确保登录的 :class:`requests.Session`（复用 :class:`SISAuth` 单例）。

    惰性导入以免模块导入期就拉起认证依赖；测试可 monkeypatch 本函数注入假
    Session（登录复用由 ``SISAuth`` 的进程内单例保证）。
    """
    from westlake_survival.sso import SISAuth

    return SISAuth().session


def _response_url(response) -> str:
    """取响应的最终 URL：优先 ``final_url``（如包装层提供），退回 ``url``。"""
    return (
        getattr(response, "final_url", None)
        or getattr(response, "url", "")
        or ""
    )


def _portal_index(session) -> str:
    """探测当前会话的门户索引（``CSPRD_x``）。

    从官网根地址的响应最终 URL 里解析；解析不到时退回
    :data:`DEFAULT_PORTAL`（不因索引探测失败而阻断请求）。
    """
    root = _PORTAL_ROOT_TEMPLATE.format(portal=DEFAULT_PORTAL)
    response = session.get(root, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    url = _response_url(response)
    match = _PORTAL_RE.search(url)
    return match.group(1) if match else DEFAULT_PORTAL


def _extract_page(response, component: str) -> str:
    """把组件页响应校验/解码为 HTML 文本，非法状态映射为库内异常。"""
    if is_offcampus(response):
        raise OffCampusError(
            "SIS 仅校园网/VPN 内可达，请先连接西湖大学 VPN 后重试。"
        )
    text = getattr(response, "text", "") or ""
    if _looks_like_login(text, _response_url(response)):
        raise AuthError(
            "SIS 会话未登录或已失效（响应为登录页/ckreq）。"
            "请确认凭据有效并已连接校园网。"
        )
    if _NOT_AUTHORIZED in text.lower():
        raise ActionError(
            f"SIS 组件页未授权（正文含 'not authorized'）：{component}。"
            "当前角色可能没有访问该组件的权限。"
        )
    return text


def fetch_page(component: str, *, query: str = "") -> str:
    """登录态 ``GET`` 任意 SIS 组件页，返回 HTML 文本。

    Args:
        component: 组件路径，如
            ``"WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL"``。
        query: 附加查询串（不含 ``?``），如 ``"Page=WL_EXAM_STU_FL"``。

    Returns:
        组件页 HTML 文本。

    Raises:
        OffCampusError: 校外访问被拒。
        AuthError: 响应是登录页（未登录 / 会话失效）。
        ActionError: 组件页对当前角色未授权（正文含 ``not authorized``）。
    """
    if not component:
        raise ValueError("component 不能为空")
    session = _session()
    portal = _portal_index(session)
    url = COMPONENT_URL_TEMPLATE.format(portal=portal, component=component)
    if query:
        url = f"{url}?{query.lstrip('?')}"
    response = session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    return _extract_page(response, component)


# --------------------------------------------------------------------------- #
# fluid 网格解析
# --------------------------------------------------------------------------- #
_TABLE_OPEN_RE = re.compile(r"<table\b[^>]*>", re.IGNORECASE)
_TABLE_ANY_RE = re.compile(r"</?table\b[^>]*>", re.IGNORECASE)


def _iter_tables(html: str):
    """逐个产出顶层 ``<table>...</table>`` 子串（嵌套表格按深度计数配对）。"""
    for match in _TABLE_OPEN_RE.finditer(html or ""):
        start = match.start()
        depth = 0
        for tag in _TABLE_ANY_RE.finditer(html, start):
            if tag.group(0).startswith("</"):
                depth -= 1
            else:
                depth += 1
            if depth == 0:
                yield html[start : tag.end()]
                break


def _table_at(html: str, start: int) -> str | None:
    """返回从 ``start``（``<table`` 位置）起配对的表格子串。"""
    depth = 0
    for tag in _TABLE_ANY_RE.finditer(html, start):
        if tag.group(0).startswith("</"):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            return html[start : tag.end()]
    return None


def _find_grid_table(html: str, grid_id: str) -> str | None:
    """按网格 id 切出目标 ``<table>``；找不到返回 ``None``。

    PeopleSoft 为同一网格会渲染「吸顶表头表」与「数据表」两张 ``<table>``，
    且**空网格**的表里不含任何 ``{grid_id}$N_row_M`` 行 id（grid id 只出现在
    容器 ``<DIV>`` 上）。故按以下顺序定位，保证选中数据表：

    1. 表内出现该网格数据行 id（``{grid_id}$N_row_M``）的 ``<table>``；
    2. 表内含 ``ps_grid-body`` / ``<tbody>`` 且正文出现网格 id 的 ``<table>``；
    3. 网格 id 出现位置之后最近的一张 ``<table>``（覆盖空网格：id 在容器 div 上）。
    """
    if not html or not grid_id:
        return None
    row_re = re.compile(rf"id=['\"]{re.escape(grid_id)}\$\d+_row_\d+['\"]")
    scoped = [table for table in _iter_tables(html) if grid_id in table]
    for table in scoped:
        if row_re.search(table):
            return table
    for table in scoped:
        if "ps_grid-body" in table or "<tbody" in table.lower():
            return table
    if scoped:
        return scoped[0]
    # 空网格兜底：grid id 在容器 div 上，取其后的第一张表。
    for match in re.finditer(rf"{re.escape(grid_id)}\$grid\$\d+", html):
        open_tag = _TABLE_OPEN_RE.search(html, match.end())
        if not open_tag:
            continue
        between = html[match.end() : open_tag.start()]
        if len(between) < 2000:  # 同容器内的紧邻表格
            table = _table_at(html, open_tag.start())
            if table:
                return table
    return None


def _normalize_cell(text: str) -> str:
    """把单元格文本规范化为「非空行以 ``\\n`` 连接」。

    容错解析器已把 ``<br />`` 记为换行；PeopleSoft 模板在 ``<br />`` 前后
    又留有真实换行，故这里按行去空白后重新拼接，多值单元格得到干净的
    ``值1\\n值2``。
    """
    lines = [line.strip() for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def parse_fluid_grid(html: str, grid_id: str) -> list[dict]:
    """解析 fluid 网格，返回「表头文本 → 单元格文本」的行字典列表。

    按 *grid_id*（如 ``WL_STU_ENRL_V2``）定位目标表格，用表头 ``th`` 文本做
    键；空表头列被跳过。单元格内 ``<br />`` 视为换行，多值以 ``\\n`` 分隔
    （:func:`_normalize_cell`）。同名表头取先出现者（与
    :func:`~westlake_survival.sis.parser._map_columns` 一致）。

    Args:
        html: 页面 HTML。
        grid_id: PeopleSoft fluid 网格 id。

    Returns:
        行字典列表；网格存在但无数据行时为空列表。

    Raises:
        ParseError: 页面里找不到该网格，或网格缺表头无法映射列。
    """
    table = _find_grid_table(html, grid_id)
    if table is None:
        raise ParseError(
            f"页面中找不到网格 {grid_id!r}，页面结构可能已变化。"
        )
    header, rows = _parse_tables(table)
    columns: dict[int, str] = {}
    used: set[str] = set()
    for index, label in enumerate(header or []):
        key = (label or "").strip()
        if not key or key in used:
            continue
        columns[index] = key
        used.add(key)
    if not columns:
        raise ParseError(
            f"网格 {grid_id!r} 未找到表头（th），无法映射列。"
        )
    result: list[dict] = []
    for cells in rows:
        record = {
            key: _normalize_cell(cells[index]) if index < len(cells) else ""
            for index, key in columns.items()
        }
        result.append(record)
    return result


# --------------------------------------------------------------------------- #
# 列名漂移守卫（2026-10-27 中文表头事故教训）
# --------------------------------------------------------------------------- #
def named_fields_empty(model) -> bool:
    """dataclass 具名字段（除 ``raw`` 兜底字典外）是否全空。

    配合 :func:`assert_named_fields` 做「表头可能又变了」的检测：sis 各数据
    模型都带 ``raw`` 原始行兜底，故具名字段判定只看非 ``raw`` 字段。
    """
    for field in dataclasses.fields(model):
        if field.name == "raw":
            continue
        value = getattr(model, field.name, None)
        if isinstance(value, str):
            if value.strip():
                return False
        elif value:
            return False
    return True


def assert_named_fields(
    rows: list[dict], models: list, *, page: str, is_empty=None
) -> None:
    """「页面有数据行但所有具名字段全空」时抛 ParseError，不静默返回空。

    背景（2026-10-27）：SIS 界面语言切中文后，只匹配英文表头的解析器把
    真实数据行全部当空行跳过、命令静默报「空」（grades 已因此修过一次
    双语映射，其余 9 条命令同根因）。静默空返回比报错更危险，故各解析器
    收尾时统一过这道闸：原始行有内容、而解析出的模型为空列表或全部
    具名字段为空 → 显式报错并列出页面实际列名，方便补双语映射。

    Args:
        rows: :func:`parse_fluid_grid` 的原始行字典列表。
        models: 解析出的模型列表（跳空行实现漂移时为空列表）。
        page: 页面名，错误消息用（如 ``"考试安排"``）。
        is_empty: 单个模型「具名字段全空」判定；缺省按 ``not model``。
            dataclass 模型传 :func:`named_fields_empty`。

    Raises:
        ParseError: 页面有数据行但所有具名字段均为空（表头可能又变化）。
    """
    data_rows = [row for row in rows if any((v or "").strip() for v in row.values())]
    if not data_rows:
        return  # 真空页 / 全空残留行：正常空数据
    blank = is_empty if is_empty is not None else (lambda m: not m)
    if models and not all(blank(m) for m in models):
        return  # 至少一行解析出了具名字段：表头匹配正常
    columns = ", ".join(key for key in data_rows[0] if key) or "（无）"
    raise ParseError(
        f"{page}：页面有 {len(data_rows)} 行数据但所有具名字段均为空，"
        f"表头可能又一次变化，已识别列：{columns}。"
    )


# --------------------------------------------------------------------------- #
# label-value 解析
# --------------------------------------------------------------------------- #
_LABEL_CLASS = "ps_box-label"
_VALUE_CLASS = "ps_box-value"
_PS_LABEL_CLASS = "ps-label"
_WS_RE = re.compile(r"\s+")

#: 空元素（HTML 里通常自闭合）：不入栈，避免残留未闭合的帧。
_VOID_TAGS = frozenset(
    {"br", "img", "input", "hr", "meta", "link", "area", "base", "col", "embed",
     "param", "source", "track", "wbr"}
)


class _LabelValueParser(HTMLParser):
    """从 PeopleSoft ``ps_box-label`` / ``ps_box-value`` 结构抽键值对。

    典型结构::

        <DIV class='ps_box-edit ...' id='win3divFOO'>
          <DIV class='ps_box-label' id='...lbl'>
            <span class='ps-label'>Credits Selected</span></DIV>
          <span class='ps_box-value' id='FOO'>84.5</span>
        </DIV>

    规则：label 元素文本非空则记为「待配对标签」；其后出现 ``ps_box-value``
    时落成一对，然后清空待配对标签。空标签（``&nbsp;``）不参与配对。同名
    标签后者覆盖前者。嵌套元素的文本在收尾时上浮到父元素缓冲，故
    ``<div class='ps_box-value'><span>x</span></div>`` 也能正确取值。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pairs: dict[str, str] = {}
        self._stack: list[dict] = []
        self._pending: str | None = None

    # -- 内部 ---------------------------------------------------------
    def _push(self, tag: str, classes: str) -> None:
        self._stack.append({"tag": tag, "cls": classes, "buf": []})

    def _close(self, tag: str) -> None:
        # 找到最近一个同名开标签；其上的嵌套元素一并按序收尾。
        while self._stack:
            element = self._stack.pop()
            self._finish(element)
            if element["tag"] == tag:
                break

    def _finish(self, element: dict) -> None:
        text = _WS_RE.sub(" ", "".join(element["buf"])).strip()
        # 文本上浮到父元素缓冲（父元素若也是 label/value 容器，仍需其内容）。
        if self._stack and text:
            self._stack[-1]["buf"].append(text)
        classes = element["cls"]
        if _LABEL_CLASS in classes or _PS_LABEL_CLASS in classes:
            if text:
                self._pending = text
        elif _VALUE_CLASS in classes:
            # 空值（如未填字段 / 空标签残余）不产出，避免噪声键。
            if self._pending is not None and text:
                self.pairs[self._pending] = text
            if self._pending is not None:
                self._pending = None

    # -- HTMLParser 钩子 ----------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "br":
            if self._stack:
                self._stack[-1]["buf"].append("\n")
            return
        if tag in _VOID_TAGS:
            return
        self._push(tag, _class_attr(attrs))

    def handle_startendtag(self, tag: str, attrs) -> None:
        # 自闭合标签（``<br/>`` / ``<img/>`` 等）不入栈；其余按单标签处理。
        if tag.lower() == "br":
            if self._stack:
                self._stack[-1]["buf"].append("\n")
            return
        if tag.lower() in _VOID_TAGS:
            return
        self._push(tag.lower(), _class_attr(attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _VOID_TAGS:
            return
        self._close(tag.lower())

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1]["buf"].append(data)

    def close(self) -> None:
        super().close()
        while self._stack:
            self._finish(self._stack.pop())


def _class_attr(attrs) -> str:
    """从属性列表取 ``class`` 值（无则空串）。"""
    for name, value in attrs:
        if name.lower() == "class":
            return value or ""
    return ""


def parse_label_values(html: str) -> dict[str, str]:
    """解析 PeopleSoft ``label-value`` 键值对页面，返回 ``{标签: 值}``。

    适用个人信息 / 学籍等以 ``ps_box-label`` + ``ps_box-value`` 呈现字段的
    页面。空标签（``&nbsp;``）与无对应值的标签不产出；同名标签后者覆盖前者。

    Args:
        html: 页面 HTML。

    Returns:
        标签到值的映射；解析不到任何对时返回空字典。
    """
    parser = _LabelValueParser()
    parser.feed(html or "")
    parser.close()
    return parser.pairs


# --------------------------------------------------------------------------- #
# PeopleSoft 主表单：动作提交
# --------------------------------------------------------------------------- #
_FORM_NAME_RE = re.compile(r"^win\d+$")


class _FormParser(HTMLParser):
    """抓第一个 ``name='winN'`` 主表单的 action 与全部 ``<input>`` 值。

    PeopleSoft 换 tab / 换下拉框都要原样回填表单状态（``ICStateNum`` 等），
    少一个字段就会被打回登录页或报 ``ICState`` 错误。表单序号随页面变化
    （实测同一产品里见过 ``win3`` / ``win4``），故按 ``win\\d+`` 匹配。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._inside = False
        self._seen = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = {name.lower(): (value or "") for name, value in attrs}
        if tag == "form" and _FORM_NAME_RE.match(attrs.get("name", "")):
            if self._seen:  # 只认第一个主表单
                return
            self._seen = True
            self._inside = True
            self.action = attrs.get("action") or self.action
            return
        if tag == "input" and self._inside and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inside:
            self._inside = False


def form_state(html: str) -> tuple[str, dict[str, str]]:
    """取 PeopleSoft 主表单的 ``(action, 字段表)``，用于回填后 POST。

    Args:
        html: 组件页 HTML。

    Returns:
        ``(表单 action URL, {input name: value})``。

    Raises:
        ParseError: 页面里没有 ``winN`` 表单（结构变化 / 未登录页）。
    """
    parser = _FormParser()
    parser.feed(html or "")
    parser.close()
    if not parser.action:
        raise ParseError("SIS 页面里找不到 winN 主表单，页面结构可能已变化。")
    return parser.action, parser.fields
