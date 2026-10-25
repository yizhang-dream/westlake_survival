"""SIS 第二课堂（Second Classroom）成绩单读取层。

入口链（2026-10-25 登录态实测）
==============================
第二课堂**不在**左侧导航菜单里（``客户化目录 → Second Classroom`` 下的两个
子目录对学生角色没有任何叶项，按导航树抓会是空的），真实入口是学生首页的
**Second Classroom 瓦片**：

1. 瓦片组件
   ``WL_AD2_MENU.WL_SEC_WEL_TILE_FL.GBL?Page=WL_SEC_WEL_TILE_FL``
   （``pStart=WL_SEC_EMPL_CLS_CM_GBL``，``ICDoModal=1&ICGrouplet=1``）；
2. 瓦片页正文里 ``LaunchURL(null,'…')`` 指向主组件，带
   ``EMPLID=<学号>&ACAD_CAREER=UGRD``：``WL_AD2_MENU.WL_SEC_EMPL_CLS_CM.GBL``；
3. 主页面左侧是 5 个维度网格（``WL_SEC_EMP_D_V1``，div 网格），右侧显示
   当前维度的要求明细；点维度是 PeopleSoft 动作
   ``ICAction=WL_SEC_EMP_WRK_DESCR100$N``（每个维度一次 POST，``win4`` 表单
   状态要逐次回填）。

页面结构
========
- 维度（h2 下 div 网格）：``责任与实践 / 学术与研究 / 体育健康 / 人文艺术 /
  团队合作``，标题形如 ``Responsibility and Practice(39%)``；
- 维度明细按 ``h3``（``chnSecStuConentInfoHear2``）分节，节内可能有
  ``h4``（``chnSecStuConentInfoHear4``）二级要求；
- 每个要求下是 fluid 网格（``WL_SEC_EMP_T_*``，真 ``<table>``）：
  ``Requirement Description`` / ``Completion Progress`` 两列，进度形如
  ``50%   24/48 (Hour(s))``。

解析容错
========
空网格（如「团队合作」下的 Activity Organizer）PeopleSoft 不渲染网格，直接
跳过；单节解析失败不影响其它节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from westlake_survival.exceptions import ParseError, WestlakeError
from westlake_survival.sis import pages
from westlake_survival.sis.pages import parse_fluid_grid

__all__ = [
    "TILE_COMPONENT",
    "TILE_QUERY",
    "REPORT_COMPONENT",
    "SecondClassRow",
    "SecondClassNode",
    "SecondClassCategory",
    "SecondClassReport",
    "second_classroom",
]

#: 首页瓦片组件（无 ``WL_CUSTOMIZE_MENU.`` 前缀，实测这个组件在 ``WL_AD2_MENU`` 菜单下）。
TILE_COMPONENT = "WL_AD2_MENU.WL_SEC_WEL_TILE_FL.GBL"
TILE_QUERY = (
    "Page=WL_SEC_WEL_TILE_FL&pStart=WL_SEC_EMPL_CLS_CM_GBL"
    "&tW=1&tH=1&ICDoModal=1&ICGrouplet=1"
)

#: 第二课堂成绩单主组件（URL 需带瓦片页给出的 ``EMPLID`` / ``ACAD_CAREER``）。
REPORT_COMPONENT = "WL_AD2_MENU.WL_SEC_EMPL_CLS_CM.GBL"

#: 瓦片页里的跳转：``LaunchURL(null,'https://…WL_SEC_EMPL_CLS_CM.GBL?…',…)``。
_LAUNCH_RE = re.compile(r"LaunchURL\(\s*null\s*,\s*'([^']+)'")

#: 维度行：``…WL_SEC_EMP_WRK_DESCR100$0…>Responsibility and Practice(39%)</a>``。
_CATEGORY_RE = re.compile(
    r"WL_SEC_EMP_WRK_DESCR100\$(\d+)'[^>]*>\s*([^<]+?)\s*</a>"
)

#: 明细分节（h3）/ 二级要求（h4）的容器类名。
_SECTION_MARK = "chnSecStuConentInfoHear2"
_GROUP_MARK = "chnSecStuConentInfoHear4"

_H3_RE = re.compile(
    r"<h3 class='ps_header-group'><span class='ps-text'[^>]*>([^<]+)</span>"
)
_H4_RE = re.compile(
    r"<h4 class='ps_header-group'><span class='ps-text'[^>]*>([^<]+)</span>"
)

#: fluid 网格数据行：``<tr class='ps_grid-row' id='WL_SEC_EMP_T_V1$0_row_3'>``。
#: 按「网格 id + 序号 + 行号」定位，同页出现多个同 id 网格时不会串行。
_ROW_RE = re.compile(
    r"<tr class='ps_grid-row' id='([A-Z0-9_]+)\$(\d+)_row_\d+'[^>]*>(.*?)</tr>",
    re.S,
)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")

#: 进度文本：``0%   0/14 (Day(s))``（中间是不换行空格）。
_PROGRESS_RE = re.compile(r"(\d+)%\s*(\d+)\s*/\s*(\d+)\s*\((.+)\)")

#: 标题末尾的百分比：``Volunteer Service(50%)``。
_PERCENT_RE = re.compile(r"^(.*?)\((\d+)%\)\s*(.*)$")

#: 「Related Information」是页面尾部工具区，不是业务分节。
_TAIL_SECTIONS = ("Related Information",)


def _clean(text: str) -> str:
    """去 HTML 实体残留与多余空白（标题里的 ``&#037;`` 等）。"""
    out = (
        str(text or "")
        .replace("&#037;", "%")
        .replace("&nbsp;", " ")
        .replace("\xa0", " ")
    )
    return re.sub(r"\s+", " ", out).strip()


def _split_percent(title: str) -> tuple[str, int | None, str]:
    """拆分 ``名称(39%)备注`` → ``(名称, 39, 备注)``。"""
    text = _clean(title)
    match = _PERCENT_RE.match(text)
    if not match:
        return text, None, ""
    name, percent, note = match.group(1).strip(), int(match.group(2)), match.group(3).strip()
    return name, percent, note


@dataclass
class SecondClassRow:
    """一条要求及其完成进度。"""

    requirement: str = ""
    progress: str = ""
    percent: int | None = None
    done: str = ""
    total: str = ""
    unit: str = ""

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "progress": self.progress,
            "percent": self.percent,
            "done": self.done,
            "total": self.total,
            "unit": self.unit,
        }

    @classmethod
    def from_row(cls, row: dict) -> "SecondClassRow":
        requirement = _pick(row, "Requirement Description", "Requirement", "Description")
        progress = _clean(_pick(row, "Completion Progress", "Progress"))
        match = _PROGRESS_RE.search(progress)
        if match:
            percent, done, total, unit = match.groups()
            return cls(
                requirement=_clean(requirement) or "—",
                progress=progress,
                percent=int(percent),
                done=done,
                total=total,
                unit=unit.strip(),
            )
        return cls(requirement=_clean(requirement) or "—", progress=progress)


@dataclass
class SecondClassNode:
    """维度下的一个要求节点（可含二级要求）。"""

    name: str = ""
    percent: int | None = None
    note: str = ""
    rows: list[SecondClassRow] = field(default_factory=list)
    children: list["SecondClassNode"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "percent": self.percent,
            "note": self.note,
            "rows": [row.to_dict() for row in self.rows],
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class SecondClassCategory:
    """一个第二课堂维度（责任与实践 / 学术与研究 / …）。"""

    name: str = ""
    percent: int | None = None
    nodes: list[SecondClassNode] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "percent": self.percent,
            "nodes": [node.to_dict() for node in self.nodes],
        }


@dataclass
class SecondClassReport:
    """第二课堂成绩单：5 个维度 + 未完成要求计数。"""

    categories: list[SecondClassCategory] = field(default_factory=list)

    @property
    def pending(self) -> int:
        """未完成（进度 <100% 或无数值）的要求条数。"""
        count = 0

        def walk(node: SecondClassNode) -> None:
            nonlocal count
            for row in node.rows:
                if row.percent is None or row.percent < 100:
                    count += 1
            for child in node.children:
                walk(child)

        for category in self.categories:
            for node in category.nodes:
                walk(node)
        return count

    def to_dict(self) -> dict:
        return {
            "categories": [category.to_dict() for category in self.categories],
            "pending": self.pending,
            "count": len(self.categories),
        }


def _pick(row: dict, *keys: str) -> str:
    """按候选表头取单元格（PeopleSoft 可能换列名大小写/后缀）。"""
    for key in keys:
        if key in row:
            return row[key]
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        if key.strip().lower() in lowered:
            return lowered[key.strip().lower()]
    return ""


def _form_state(html: str) -> tuple[str, dict[str, str]]:
    """取 winN 主表单状态（委托共享读取层）。"""
    return pages.form_state(html)


def _fetch_report(session) -> tuple[str, str, dict[str, str]]:
    """打开第二课堂主组件，返回 ``(HTML, 表单 action, 表单字段)``。

    走瓦片页而不是直接拼组件地址：主组件 URL 需要瓦片页给出的
    ``EMPLID`` / ``ACAD_CAREER``（学号不写死在本模块里）。
    """
    portal = pages._portal_index(session)
    tile_url = pages.COMPONENT_URL_TEMPLATE.format(portal=portal, component=TILE_COMPONENT)
    tile_url = f"{tile_url}?{TILE_QUERY}"
    tile_response = session.get(tile_url, timeout=30, allow_redirects=True)
    tile_html = pages._extract_page(tile_response, TILE_COMPONENT)

    match = _LAUNCH_RE.search(tile_html)
    if not match:
        raise ParseError(
            "第二课堂瓦片页里找不到 LaunchURL 跳转，页面结构可能已变化。"
        )
    report_url = match.group(1)
    response = session.get(report_url, timeout=30, allow_redirects=True)
    html = pages._extract_page(response, REPORT_COMPONENT)
    action, fields = pages.form_state(html)
    return html, action, fields


def _categories(html: str) -> list[SecondClassCategory]:
    """从首页左侧网格取维度名与百分比（按动作序号排序）。"""
    found: dict[int, SecondClassCategory] = {}
    for index, title in _CATEGORY_RE.findall(html or ""):
        name, percent, _ = _split_percent(title)
        if not name or int(index) in found:
            continue
        found[int(index)] = SecondClassCategory(name=name, percent=percent)
    if not found:
        raise ParseError("第二课堂页面里找不到维度网格，页面结构可能已变化。")
    return [found[index] for index in sorted(found)]


def _rows(chunk: str) -> list[SecondClassRow]:
    """解析一个要求块里的全部网格行（按「网格 id + 序号」逐行取，避免串行）。

    列名从同 id 的网格表头取（:func:`parse_fluid_grid`）；同页多个同 id
    网格（不同 ``$N`` 序号）时列名相同、行各自独立。
    """
    columns: dict[str, list[str]] = {}
    rows: list[SecondClassRow] = []
    for match in _ROW_RE.finditer(chunk or ""):
        grid_id, body = match.group(1), match.group(3)
        if grid_id not in columns:
            try:
                parsed = parse_fluid_grid(chunk, grid_id)
            except WestlakeError:
                parsed = []
            columns[grid_id] = list(parsed[0].keys()) if parsed else []
        keys = columns[grid_id]
        if not keys:
            continue
        cells = [
            _clean(_TAG_RE.sub(" ", cell)) for cell in _CELL_RE.findall(body)
        ]
        if len(cells) == len(keys) + 1:  # 首列是行号，丢弃
            cells = cells[1:]
        rows.append(SecondClassRow.from_row(dict(zip(keys, cells))))
    return rows


def _node(chunk: str, title: str) -> SecondClassNode:
    """把一个 h4 要求块转成节点（含自身网格行）。"""
    name, percent, note = _split_percent(title)
    return SecondClassNode(name=name, percent=percent, note=note, rows=_rows(chunk))


def _sections(chunk: str) -> list[SecondClassNode]:
    """把维度明细按 h3 分节，节内的 h4 作为子节点。"""
    nodes: list[SecondClassNode] = []
    for raw in (chunk or "").split(_SECTION_MARK)[1:]:
        heading = _H3_RE.search(raw)
        if not heading:
            continue
        name, percent, note = _split_percent(heading.group(1))
        if name in _TAIL_SECTIONS:
            continue
        groups = raw.split(_GROUP_MARK)[1:]
        if groups:
            children = []
            for group in groups:
                sub = _H4_RE.search(group)
                if not sub:
                    continue
                children.append(_node(group, sub.group(1)))
            node = SecondClassNode(name=name, percent=percent, note=note, children=children)
            # h4 块之外的直属网格行（少见，兜底保留）
            head = raw.split(_GROUP_MARK)[0]
            node.rows = _rows(head)
        else:
            node = SecondClassNode(name=name, percent=percent, note=note, rows=_rows(raw))
        nodes.append(node)
    return nodes


def _select_category(session, action: str, fields: dict[str, str], index: int) -> str:
    """点第 *index* 个维度（``ICAction=WL_SEC_EMP_WRK_DESCR100$N``）。"""
    data = dict(fields)
    data["ICAction"] = f"WL_SEC_EMP_WRK_DESCR100${index}"
    response = session.post(action, data=data, timeout=40, allow_redirects=True)
    return pages._extract_page(response, REPORT_COMPONENT)


def second_classroom() -> SecondClassReport:
    """取第二课堂成绩单（5 个维度 + 每项要求进度）。

    每次调用 6 个请求：瓦片页 → 主页面 → 其余 4 个维度各一次 POST。

    Raises:
        OffCampusError: 校外访问被拒。
        AuthError: 会话失效。
        ActionError: 组件对当前角色未授权。
        ParseError: 页面结构变化（找不到瓦片跳转 / 维度网格 / win4 表单）。
    """
    session = pages._session()
    html, action, fields = _fetch_report(session)
    report = SecondClassReport(categories=_categories(html))

    page_html = html
    for index, category in enumerate(report.categories):
        if index:
            page_html = _select_category(session, action, fields, index)
            action, fields = _form_state(page_html)
        category.nodes = _sections(page_html)
    return report
