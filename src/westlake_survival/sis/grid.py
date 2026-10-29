"""周课表网格与冲突检测（只读；对标 sustech_survival 的 conflict-free schedule 视图）。

输入 :class:`~westlake_survival.sis.parser.ClassSession` 列表（如
``sis.get_schedule()`` 的返回），或 WebUI 课表行的 dict 列表
（``name`` / ``weekday`` / ``time`` ``"HH:MM-HH:MM"``）。输出一周网格
与冲突清单。选课窗口开放后，可把选课车节次一并喂入做「课表 + 选课车」
的冲突预检——写操作仍不做（边界见 consequence.py 与 SKILL.md）。
"""
from __future__ import annotations

from typing import Any, Iterable

WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")

#: 网格时间轴的固定小时范围（campus hours；数据超出时自动扩展）。
GRID_HOURS = range(8, 23)


def _label(session_or_row: Any) -> str:
    """课程格子的短标签：优先课名，退课程代码，截 6 字。"""
    name = getattr(session_or_row, "title", None) or (
        session_or_row.get("name") if isinstance(session_or_row, dict) else ""
    )
    code = getattr(session_or_row, "course_code", None) or (
        session_or_row.get("course") if isinstance(session_or_row, dict) else ""
    )
    text = (name or code or "—").strip()
    return text[:6]


def _slots(seq: Iterable[Any]) -> list[tuple[str, int, int, int, str, str]]:
    """归一为 ``(label, weekday, start_min, end_min, 起止文本, 地点)``。

    接受 ``ClassSession`` 或 WebUI 行 dict；时间为 ``00:00-00:00`` /
    解析失败的条目跳过（视为无结构时间）。
    """
    out = []
    for item in seq:
        if isinstance(item, dict):
            weekday = item.get("weekday")
            time_text = str(item.get("time") or "")
            room = str(item.get("location") or "")
        else:
            weekday = item.weekday
            time_text = (
                f"{item.start_time.strftime('%H:%M')}-{item.end_time.strftime('%H:%M')}"
            )
            room = item.room or ""
        if not isinstance(weekday, int) or not 1 <= weekday <= 7:
            continue
        try:
            a, _, b = time_text.partition("-")
            start = int(a[:2]) * 60 + int(a[3:5])
            end = int(b[:2]) * 60 + int(b[3:5])
        except (ValueError, IndexError):
            continue
        if start >= end:
            continue
        out.append((_label(item), weekday, start, end, time_text, room))
    return out


def detect_conflicts(seq: Iterable[Any]) -> list[str]:
    """同一 weekday 时间区间重叠（且周次交集非空，若双方都带周次）→ 冲突清单。

    周次信息只在 ``ClassSession`` 上有；行 dict 视为每周（宁可多报不漏报）。
    """
    def _weeks(item: Any) -> set[int] | None:
        weeks = getattr(item, "weeks", None)
        return set(weeks) if weeks is not None else None

    items = list(seq)
    slots = _slots(items)
    out = []
    for i in range(len(slots)):
        for j in range(i + 1, len(slots)):
            la, da, sa, ea, ta, _ = slots[i]
            lb, db, sb, eb, tb, _ = slots[j]
            if da != db or max(sa, sb) >= min(ea, eb):
                continue
            # 同课同起止 = 同一节次按班级/教室拆出的平行条目（实测 General
            # Physics 一节三教室），不是冲突。
            if la == lb and sa == sb and ea == eb:
                continue
            wa, wb = _weeks(items[i]), _weeks(items[j])
            if wa is not None and wb is not None and not (wa & wb):
                continue
            overlap = f"{max(sa, sb) // 60:02d}:{max(sa, sb) % 60:02d}-{min(ea, eb) // 60:02d}:{min(ea, eb) % 60:02d}"
            out.append(f"周{WEEKDAY_CN[da - 1]} {overlap}：{la} × {lb}（{ta} / {tb}）")
    return out


def render_text(seq: Iterable[Any]) -> str:
    """一周文字网格：行=小时，列=周一..周日；冲突格前置 ⚠ 并在末尾列清单。"""
    slots = _slots(seq)
    if not slots:
        return "（无带时间的课表节次，网格为空）"
    conflicts = detect_conflicts(seq)
    grid: dict[tuple[int, int], str] = {}
    cell_conflict: set[tuple[int, int]] = set()
    for label, weekday, start, end, _, _ in slots:
        for hour in range(start // 60, (end - 1) // 60 + 1):
            key = (weekday, hour)
            if key in grid and grid[key] != label:
                cell_conflict.add(key)
            grid.setdefault(key, label)
    hours = sorted({hour for (_, hour) in grid})
    lines = ["      " + "".join(f"周{WEEKDAY_CN[d - 1]}   " for d in range(1, 8))]
    for hour in hours:
        row = f"{hour:02d}:00 "
        for day in range(1, 8):
            cell = grid.get((day, hour))
            mark = "⚠" if (day, hour) in cell_conflict else " "
            row += f"{mark}{cell or '·'}".ljust(6)
        lines.append(row)
    lines.append("")
    if conflicts:
        lines.append(f"冲突 {len(conflicts)} 处：")
        lines.extend(f"- {c}" for c in conflicts)
    else:
        lines.append("冲突：0 处。选课窗口开放后可把选课车节次一并喂入预检（只读）。")
    return "\n".join(lines)
