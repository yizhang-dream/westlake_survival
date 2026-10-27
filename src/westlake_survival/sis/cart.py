"""SIS 选课车（Study Shopping Cart）只读视图。

数据源（2026-10-27 接入）：组件页 ``SSR_STUDENT_FL.SSR_SHOP_CART_FL.GBL``
（probe 常量同源，见 ``cli.main.SIS_SHOP_CART_COMPONENT``；audit 2026-10-27
实测该组件对学生角色**已授权**）。解析委托
:mod:`westlake_survival.sis.pages`（登录态抓页 + fluid 网格解析），本模块只
负责网格定位与列名归一——与 :mod:`westlake_survival.sis.exams` 完全同构。

**只读**：本模块只 ``GET`` 选课车页面并解析展示；PeopleSoft 选课车的
add / drop / swap 全是表单 POST 写操作，按项目政策一律不做（连预检都不做）。
「可选课程/余量检索」（SSR_START_FL 类组件）未在承诺范围内，留待后续
侦察组件授权后再议。

网格 id 说明
============
选课车 fluid 网格的具体 id（PeopleSoft 通常形如 ``SSR_SHOP_CART_VW``）以
页面实际渲染为准：本模块按「已知候选 + 页面行 id 自动发现」两级定位，
逐个尝试直到解析出带具名字段的行；空购物车时页面仍有网格容器
（``<id>$grid$N`` 无数据行），自动发现同样覆盖，返回空列表（CLI 打印
明确空态）。全部候选都解析失败才抛 :class:`ParseError` 并列出已发现的
网格 id，绝不静默返回空。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from westlake_survival.exceptions import ActionError, ParseError
from westlake_survival.sis import pages

__all__ = [
    "CART_COMPONENT",
    "CART_GRID_CANDIDATES",
    "CartCourse",
    "shopping_cart",
]

#: 选课车组件页（与 cli/main.py 的 probe 常量同源）。
CART_COMPONENT = "SSR_STUDENT_FL.SSR_SHOP_CART_FL.GBL"

#: 选课车网格 id 候选（标准 PeopleSoft 命名优先；实际以页面自动发现为准）。
CART_GRID_CANDIDATES = ("SSR_SHOP_CART_VW", "SSR_SHOP_CART_GRID", "SSR_CART_VW")

#: 页面里网格数据行 id 形态（``<grid>$N_row_M``）。
_GRID_ROW_RE = re.compile(r"id=['\"]([A-Za-z][A-Za-z0-9_]*)\$\d+_row_\d+['\"]")

#: 空网格的容器 id 形态（``<grid>$grid$N``，无数据行时仍存在；容器 div 通常
#: 带 ``win0div`` 前缀，如 ``win0divSSR_SHOP_CART_VW$grid$0``）。
_GRID_CONTAINER_RE = re.compile(r"id=['\"]((?:win0div)?[A-Za-z][A-Za-z0-9_]*)\$grid\$\d+['\"]")


@dataclass
class CartCourse:
    """选课车里暂存的一门课程。

    Attributes:
        course_code: 课程代码（如 ``PHY 1004``）。
        course_title: 课程名称。
        units: 学分（页面原文）。
        status: 状态（如 Open / Closed / 待提交等页面原文）。
        extra: 其余无法归一的列（如节次/教师），键为页面表头原文。
    """

    course_code: str = ""
    course_title: str = ""
    units: str = ""
    status: str = ""
    extra: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}

    #: 表头双语文备（写法沿用 exams.ExamSlot._COLUMNS；登录语言中英皆可）。
    _COLUMNS = {
        "course_code": ("Course Code", "课程代码", "课程编号"),
        "course_title": ("Course Title", "课程名称", "标题"),
        "units": ("Units", "学分", "学分/Units"),
        "status": ("Status", "状态"),
    }

    @classmethod
    def from_row(cls, row: dict) -> "CartCourse":
        """从 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 行字典构造。

        具名列表头逐列取第一个命中的语言键；未归一的列进 ``extra``。
        """
        def pick(*names: str) -> str:
            for name in names:
                value = row.get(name)
                if value:
                    return str(value).strip()
            return ""

        known = {name for names in cls._COLUMNS.values() for name in names}
        extra = {k: v for k, v in row.items() if k not in known and (v or "").strip()}
        return cls(
            course_code=pick(*cls._COLUMNS["course_code"]),
            course_title=pick(*cls._COLUMNS["course_title"]),
            units=pick(*cls._COLUMNS["units"]),
            status=pick(*cls._COLUMNS["status"]),
            extra=extra,
        )

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "course_code": self.course_code,
            "course_title": self.course_title,
            "units": self.units,
            "status": self.status,
            "extra": self.extra,
        }

    def named_fields_empty(self) -> bool:
        """具名字段（除 extra 兜底外）是否全空——配合表头漂移检测。"""
        return not (self.course_code or self.course_title or self.units or self.status)


def _grid_container_id(name: str) -> str:
    """剥掉容器 div 的 ``win0div`` 前缀，得到网格记录名。"""
    return name[len("win0div"):] if name.startswith("win0div") else name


#: 未授权页的正文标记。PeopleSoft 按界面语言给英文或中文文案，
#: 只认英文会把「您无权访问该页面」当成正常空页（数据静默变空）。
_UNAUTHORIZED_MARKERS = ("not authorized", "您无权访问", "无权访问该页面", "you are not authorized")


def _assert_page_authorized(html: str) -> None:
    """页面若为「未授权」拒绝页则抛 ActionError，避免报成结构变化。

    这类页 HTTP 200、无网格、正文一句话，前面的解析器只会给出「找不到网格」
    这种误导性结论；调用方需要知道是权限而不是解析问题。
    """
    lowered = html.lower()
    if any(marker.lower() in lowered for marker in _UNAUTHORIZED_MARKERS):
        raise ActionError(
            "选课车组件未授权（页面正文：您无权访问该页面）——该角色当前没有"
            "选课车权限（选课窗口未开或未开放本角色）"
        )


def _cart_rows(html: str) -> list[dict]:
    """定位选课车网格并解析为行字典列表。

    两级定位：已知候选 id 优先，再按页面 ``<grid>$N_row_M`` /
    ``<grid>$grid$N`` id 自动发现。判定顺序：

    1. 逐个网格解析，第一个出现「带具名字段行」的即选课车网格；
    2. 整页无任何数据行时：恰好一个网格容器（空表或连表头都没渲染）→
       空购物车；多个容器或无任何容器 → 抛错列出，绝不猜。
    """
    _assert_page_authorized(html)
    discovered = list(dict.fromkeys(_GRID_ROW_RE.findall(html)))
    discovered += [
        _grid_container_id(g)
        for g in dict.fromkeys(_GRID_CONTAINER_RE.findall(html))
        if _grid_container_id(g) not in discovered
    ]
    ordered = [g for g in CART_GRID_CANDIDATES if g not in discovered] + discovered
    has_data_rows = bool(_GRID_ROW_RE.search(html))
    containers = {
        _grid_container_id(g) for g in _GRID_CONTAINER_RE.findall(html)
    }
    failures: list[str] = []
    empty_grids: list[str] = []
    for grid_id in ordered:
        try:
            rows = pages.parse_fluid_grid(html, grid_id)
        except ParseError as exc:
            message = str(exc)
            failures.append(f"{grid_id}: {message}")
            # 空车特例：整页无数据行、容器 div 在页面上（正则独立核实），
            # 其周边没有可解析表格或表格无表头——视为空购物车
            # （PeopleSoft 空网格可以连表头表都不渲染）。
            if not has_data_rows and grid_id in containers and (
                "未找到表头" in message or "找不到网格" in message
            ):
                empty_grids.append(grid_id)
            continue
        models = [CartCourse.from_row(r) for r in rows]
        if any(not m.named_fields_empty() for m in models):
            return rows
        if not rows:
            empty_grids.append(grid_id)
        else:
            failures.append(f"{grid_id}: 有 {len(rows)} 行但具名字段全空（表头漂移）")
    if len(empty_grids) == 1:
        return []  # 唯一空网格：空购物车
    if empty_grids:
        raise ParseError(
            "页面发现多个空网格，无法确定选课车网格：" + "、".join(empty_grids)
        )
    if failures:
        raise ParseError(
            "选课车网格解析失败：" + "；".join(failures[:4])
            + "。表头可能变化或页面结构变化，请反馈。"
        )
    raise ParseError("选课车页面未识别到任何网格（候选与页面自动发现均失败）。")


def shopping_cart() -> list[CartCourse]:
    """取选课车内容（**只读**；不做任何 add/drop/swap 写操作）。

    Returns:
        :class:`CartCourse` 列表；购物车为空时为空列表（CLI 打印明确空态）。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 组件未授权（选课窗口未开）。
        ParseError: 网格识别失败，或页面有数据行但所有具名字段均为空
            （:func:`~westlake_survival.sis.pages.assert_named_fields` 防静默空）。
    """
    html = pages.fetch_page(CART_COMPONENT)
    rows = _cart_rows(html)
    result = [CartCourse.from_row(row) for row in rows]
    result = [c for c in result if not c.named_fields_empty()]
    pages.assert_named_fields(rows, result, page="选课车", is_empty=CartCourse.named_fields_empty)
    return result
