"""SIS 评教中心页读取：把 fluid 网格 ``WL_EVAL_WRK`` 解析为 :class:`EvalTask`。

数据源（2026-09-23 实测）：组件页
``WL_CUSTOMIZE_MENU.WL_STU_EVAL_CEN.GBL``（页面标题「Evaluation Center」），
查询串 ``page=WL_STU_EVAL_CEN``，fluid 网格 ``WL_EVAL_WRK``，实测 25 行。
列（按真页 ``th`` 表头原样）：``课程学历 / Term / Course Code / Course Title /
Class / Evaluate Category / Date/Time / Evaluation Status / Detail``。

**status 取值集合（实测）**：真页 25 行 ``Evaluation Status`` **全部为**
``Submit``，未见其它取值；``Evaluate Category`` 全部为 ``End``。站点未在页面上
提供状态图例，故 :data:`COMPLETED_STATUSES`（已完成标记集合）按 PeopleSoft
评教组件的常见收尾标记**保守**取值，其中**没有任何一项在真页出现过**——
真页若出现新状态值，pending 判定需据此复核（见 :func:`pending_evaluations`）。

**period 拆分**：``Date/Time`` 形如 ``2026/06/02 10:00 - 2026/06/26 23:59``
（起止以 `` - `` 连接）。本模块把原始串保留在 ``period_raw``，同时按首个
`` - `` 拆出 ``period_start`` / ``period_end``；无分隔符时整串进 ``period_start``、
``period_end`` 为空串（不臆造）。

**detail_url**：真页 ``Detail`` 列是 PeopleSoft 的 JS 按钮
（``javascript:submitAction_win3(...)``，**无真实 URL**），故本模块无法从
网格取到可请求的地址，``detail_url`` 恒为空串（字段保留以便未来页面提供链接）。

解析委托给 :mod:`westlake_survival.sis.pages`（登录态抓页 + fluid 网格解析），
本模块只负责列名归一与数据模型映射。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import click

from westlake_survival.exceptions import OffCampusError, WestlakeError
from westlake_survival.sis import pages

__all__ = [
    "EVALS_COMPONENT",
    "EVALS_QUERY",
    "EVALS_GRID_ID",
    "COMPLETED_STATUSES",
    "EvalTask",
    "evaluations",
    "pending_evaluations",
    "cli_group",
]

#: 评教中心组件。
EVALS_COMPONENT = "WL_CUSTOMIZE_MENU.WL_STU_EVAL_CEN.GBL"

#: 评教中心查询串（``page`` 参数指向评教 fluid 页）。
EVALS_QUERY = "page=WL_STU_EVAL_CEN"

#: 评教 fluid 网格 id。
EVALS_GRID_ID = "WL_EVAL_WRK"

#: 已完成状态标记集合（用于 :func:`pending_evaluations` 的「非已完成」判定）。
#:
#: **重要**：2026-09-23 实测真页 25 行状态全部为 ``Submit``，下述标记**均未
#: 在真页出现过**；站点也未提供状态图例。这里按 PeopleSoft 评教组件常见的
#: 收尾标记保守取值，仅作「什么算已完成」的可覆盖口径。若真页出现新值，
#: 应据此集合复核 pending 判定。
COMPLETED_STATUSES = frozenset(
    {"Submitted", "Completed", "Complete", "Finished", "Evaluated"}
)

#: ``Date/Time`` 起止分隔符。
_PERIOD_SEP = " - "


@dataclass
class EvalTask:
    """一条待评 / 已评的教学评估任务。

    Attributes:
        term: 学期描述（如 ``2026-2027 Fall Term``）。
        course_code: 课程代码（如 ``ENG1003``）。
        course_title: 课程名称（ENG locale）。
        class_nbr: 教学班号（真页 ``Class`` 列，如 ``1010``）。
        category: 评估类别（真页 ``Evaluate Category`` 列，实测 ``End``）。
        period_start: 评估时间区间起（如 ``2026/06/02 10:00``）；无区间时为空串。
        period_end: 评估时间区间止（如 ``2026/06/26 23:59``）；无区间时为空串。
        period_raw: ``Date/Time`` 原始串（如 ``2026/06/02 10:00 - 2026/06/26 23:59``）。
        status: 评估状态（实测 ``Submit``）；缺失时为空串。
        detail_url: 详情地址；真页 Detail 为 JS 按钮无 URL，恒为空串。
    """

    term: str = ""
    course_code: str = ""
    course_title: str = ""
    class_nbr: str = ""
    category: str = ""
    period_start: str = ""
    period_end: str = ""
    period_raw: str = ""
    status: str = ""
    detail_url: str = ""

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "term": self.term,
            "course_code": self.course_code,
            "course_title": self.course_title,
            "class_nbr": self.class_nbr,
            "category": self.category,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_raw": self.period_raw,
            "status": self.status,
            "detail_url": self.detail_url,
        }

    @classmethod
    def from_row(cls, row: dict) -> "EvalTask":
        """从 :func:`~westlake_survival.sis.pages.parse_fluid_grid` 的行字典构造。

        列名以真页 ``th`` 文本为准，并对 ``Class``/``Class Nbr``、
        ``Evaluate Category``/``Category``、``Date/Time``/``Date-Time``、
        ``Evaluation Status``/``Status`` 等常见变体做别名兜底。
        """
        period_raw = _pick(row, "Date/Time", "Date-Time", "DateTime").strip()
        start, end = _split_period(period_raw)
        return cls(
            term=_pick(row, "Term").strip(),
            course_code=_pick(row, "Course Code").strip(),
            course_title=_pick(row, "Course Title").strip(),
            class_nbr=_pick(row, "Class", "Class Nbr").strip(),
            category=_pick(row, "Evaluate Category", "Category").strip(),
            period_start=start,
            period_end=end,
            period_raw=period_raw,
            status=_pick(row, "Evaluation Status", "Status").strip(),
            detail_url=_pick(row, "Detail URL", "Detail Url").strip(),
        )


def _pick(row: dict, *keys: str) -> str:
    """按顺序取第一个存在且非 None 的列值（缺失列返回空串）。"""
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return ""


def _split_period(raw: str) -> tuple[str, str]:
    """把 ``Date/Time`` 原始串拆成 ``(起, 止)``；无分隔符时止为空串。"""
    if not raw:
        return "", ""
    if _PERIOD_SEP not in raw:
        return raw, ""
    start, end = raw.split(_PERIOD_SEP, 1)
    return start.strip(), end.strip()


def evaluations() -> list[EvalTask]:
    """取评教中心全部评估任务（按页面顺序）。

    Returns:
        :class:`EvalTask` 列表；页面无数据行时为空列表。缺课程信息的空行被跳过。

    Raises:
        AuthError: 会话失效。
        OffCampusError: 校外访问被拒。
        ActionError: 评教组件未授权。
        ParseError: 页面结构变化导致网格解析失败。
    """
    html = pages.fetch_page(EVALS_COMPONENT, query=EVALS_QUERY)
    result: list[EvalTask] = []
    for row in pages.parse_fluid_grid(html, EVALS_GRID_ID):
        task = EvalTask.from_row(row)
        if not (task.course_code or task.course_title):
            continue  # 站点残留的空行
        result.append(task)
    return result


def pending_evaluations() -> list[EvalTask]:
    """取尚未完成的评估任务（``status`` 非空且不在 :data:`COMPLETED_STATUSES`）。

    已完成口径见 :data:`COMPLETED_STATUSES`：真页（2026-09-23）25 行状态全部为
    ``Submit``，该集合中的标记均未在真页出现，故当前真页下本函数返回全部 25 行
    ——即站点未把任何一条标记为已完成。``status`` 为空串时视为「无法判定」，
    不计入 pending（避免臆断）。

    Returns:
        未完成 :class:`EvalTask` 列表（保持页面顺序）。
    """
    return [
        task
        for task in evaluations()
        if task.status and task.status not in COMPLETED_STATUSES
    ]


# --------------------------------------------------------------------------- #
# CLI（注册由后续集成单元完成；本模块只定义 ``cli_group``）
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


@click.group(name="sis-evals", help="评教中心：列出评估任务 / 待评任务。")
def cli_group() -> None:
    """``westlake sis-evals`` 命令组（注册由后续集成单元完成）。"""


@cli_group.command(name="list")
@click.option("--pending", is_flag=True, help="只看尚未完成的评估任务。")
@_handle_errors
def sis_evals_list(pending: bool) -> None:
    """列出评估任务（默认全部；``--pending`` 只看未完成）。"""
    from westlake_survival.cli.main import _print_table

    items = pending_evaluations() if pending else evaluations()
    if not items:
        click.echo("无评估任务。")
        return
    rows = [
        (
            task.term or "—",
            task.course_code or "—",
            task.course_title or "—",
            task.class_nbr or "—",
            task.category or "—",
            task.period_raw or "—",
            task.status or "—",
        )
        for task in items
    ]
    _print_table(rows, ("学期", "课程代码", "课程名称", "班级", "类别", "评估时间", "状态"))