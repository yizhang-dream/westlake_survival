"""把 SIS 课表节次导出为 iCalendar (``.ics``) 文本。

纯手写 RFC 5545 字符串（不依赖第三方 ics 库），与
:mod:`westlake_survival.transit.ical` 同风格：

- 时间用**浮动本地时间**（``YYYYMMDDTHHMMSS``，无 ``Z``、无 ``TZID``），
  客户端按本地时区显示。课表时间本就是中国标准时间 UTC+8，浮动时间避免了
  为 ``Asia/Shanghai`` 附带 VTIMEZONE 的复杂度（``VTIMEZONE`` 因此省略）。
- 每个 :class:`~westlake_survival.sis.ClassSession` 按「日期范围 + 星期几」
  展开为**逐日 VEVENT**（而非 RRULE）：逐日展开对「单次课」「周次不连续」
  「同一课多个 meeting pattern」都更直观，也便于按 :attr:`ClassSession.weeks`
  精确过滤非上课周。
- UID 规则：``wl-sis-{course_code}-{weekday}-{start}-{date}@westlake_survival``，
  同一 UID 只出现一次（去重）。字段做 RFC 5545 TEXT 转义并折行。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from westlake_survival.sis.parser import ClassSession

__all__ = ["courses_to_ical", "save_ics", "PRODID", "CALENDAR_NAME", "UID_SUFFIX"]

#: iCalendar PRODID。
PRODID = "-//westlake_survival//CN"

#: 默认日历名。
CALENDAR_NAME = "西湖大学课表"

#: UID 域名后缀。
UID_SUFFIX = "westlake_survival"

#: 视为「无效日期」的年份下界（解析失败时 :class:`ClassSession` 用 1970 哨兵）。
_MIN_VALID_YEAR = 2000


def _escape_text(value: str) -> str:
    """RFC 5545 TEXT 转义：反斜杠、分号、逗号、换行。"""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """按 RFC 5545 折行：每行不超过 75 个八位组，续行以空格开头。

    按字符边界切分（**不切开多字节 UTF-8 字符**），首行 ≤75 字节，
    续行 ≤74 字节（加前导空格共 75）。
    """
    if len(line.encode("utf-8")) <= 75:
        return line
    chunks: list[str] = []
    current = ""
    current_bytes = 0
    limit = 75
    for char in line:
        size = len(char.encode("utf-8"))
        if current_bytes + size > limit:
            chunks.append(current)
            current = char
            current_bytes = size
            limit = 74
        else:
            current += char
            current_bytes += size
    if current:
        chunks.append(current)
    return "\r\n ".join(chunks)


def _clock(value) -> str:
    """``time`` → ``HHMMSS``。"""
    return f"{value.hour:02d}{value.minute:02d}{value.second:02d}"


def _uid(session: ClassSession, day: date) -> str:
    code = session.course_code or "course"
    start = _clock(session.start_time)
    # room 参与 UID：同一门课同日同时段分教室上（小班/多 meeting pattern）
    # 是不同事件，缺了会被去重逻辑静默丢弃。
    room = (session.room or "").strip() or "noro"
    return (
        f"wl-sis-{code}-{session.weekday}-{start}-{room}-{day.strftime('%Y%m%d')}"
        f"@{UID_SUFFIX}"
    )


def _week1_monday(sessions: Sequence[ClassSession]) -> date | None:
    """推算第 1 周的周一：所有有效 ``date_start`` 中最早者所在周的周一。

    边界条件（**与 wzsyyh/westlake-ics 语义一致，不另行修正**）：锚点取的是
    *全局* 最早 ``date_start``，而非某个固定学期起始日。因此若学生最早的一门课
    本身就从第 2 周（或更晚）开始，所有周号会整体偏移——例如某课标称
    ``weeks=(1,)`` 但它是全局最早的课，它实际发生的日期就会被当作"第 1 周"。
    这是 SIS 课表页周次与 ``date_start`` 之间固有的口径差；如出现偏移，
    以 SIS 课表页显示的周次为准。返回 ``None`` 表示无有效日期，此时
    ``weeks`` 过滤不生效（区间内每周都产出）。
    """
    starts = [
        s.date_start
        for s in sessions
        if s.date_start.year >= _MIN_VALID_YEAR
    ]
    if not starts:
        return None
    earliest = min(starts)
    return earliest - timedelta(days=earliest.weekday())


def _iter_days(session: ClassSession, week1_monday: date | None) -> Iterable[date]:
    """枚举该节次实际发生的每一天。

    - 日期范围无效（年份 < 2000）或 ``date_start > date_end`` → 不产出；
    - 仅取 ``isoweekday() == session.weekday`` 的日期；
    - ``session.weeks`` 不为 ``None`` 时，按「第 1 周周一」推算的周次过滤。
    """
    start, end = session.date_start, session.date_end
    if start.year < _MIN_VALID_YEAR or end.year < _MIN_VALID_YEAR:
        return
    if end < start:
        start, end = end, start
    # 对齐到范围内第一个目标星期几。
    delta = (session.weekday - start.isoweekday()) % 7
    day = start + timedelta(days=delta)
    weeks = session.weeks
    while day <= end:
        if weeks is None or week1_monday is None:
            yield day
        else:
            week_no = (day - week1_monday).days // 7 + 1
            if week_no in weeks:
                yield day
        day += timedelta(days=7)


def courses_to_ical(
    sessions: Sequence[ClassSession],
    *,
    cal_name: str = CALENDAR_NAME,
    week1_monday: date | None = None,
    now: datetime | None = None,
) -> str:
    """把课表节次生成完整 VCALENDAR 文本（CRLF 换行）。

    Args:
        sessions: :class:`~westlake_survival.sis.ClassSession` 列表。
        cal_name: 日历显示名（``X-WR-CALNAME``）。
        week1_monday: 第 1 周的周一（``weeks`` 过滤用）；``None`` 时按所有
            有效 ``date_start`` 中最早者所在周的周一推算。注意该锚点是
            **全局最早** 日期所在周（见 :func:`_week1_monday`），而非固定学期
            起始日：若最早一门课从第 2 周起，周号会整体偏移；如出现偏移，
            以 SIS 课表页周次为准。
        now: ``DTSTAMP`` 时刻（测试用）；``None`` 用当前 UTC 时间。

    Returns:
        完整的 VCALENDAR 字符串。

    边界：``week1_monday`` 显式给出时以传入值为准；无法推算（无有效
    ``date_start``）时 ``weeks`` 过滤不生效，按日期范围逐周产出。
    """
    sessions = list(sessions or [])
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    anchor = week1_monday or _week1_monday(sessions)

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(cal_name)}",
    ]

    seen: set[str] = set()
    for session in sessions:
        summary = _escape_text(session.title or session.course_code)
        location = _escape_text(session.room)
        description_parts = []
        if session.teacher:
            description_parts.append(session.teacher)
        if session.course_code:
            description_parts.append(session.course_code)
        description = _escape_text(" / ".join(description_parts))
        start_clock = _clock(session.start_time)
        end_clock = _clock(session.end_time)

        for day in _iter_days(session, anchor):
            uid = _uid(session, day)
            if uid in seen:
                continue
            seen.add(uid)
            day_text = day.strftime("%Y%m%d")
            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{uid}")
            lines.append(f"DTSTAMP:{stamp}")
            lines.append(f"DTSTART:{day_text}T{start_clock}")
            lines.append(f"DTEND:{day_text}T{end_clock}")
            if summary:
                lines.append(f"SUMMARY:{summary}")
            if location:
                lines.append(f"LOCATION:{location}")
            if description:
                lines.append(f"DESCRIPTION:{description}")
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def save_ics(sessions: Sequence[ClassSession], path: str | Path) -> Path:
    """把课表写成 ``.ics`` 文件，返回写入的 :class:`~pathlib.Path`。"""
    destination = Path(path)
    if destination.parent and not destination.parent.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(courses_to_ical(sessions), encoding="utf-8")
    return destination