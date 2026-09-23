"""把班车时刻表导出为 iCalendar (``.ics``) 文本。

纯手写 RFC 5545 字符串，不依赖第三方 ics 库：

- 时间用 **浮动本地时间**（``YYYYMMDDTHHMMSS``，无 ``Z``、无 ``TZID``），
  客户端按本地时区显示；避免为 ``Asia/Shanghai`` 附带 VTIMEZONE 的复杂度。
- 每个 ``(校区, 日别)`` 组合，对未来 ``weekdays_ahead`` 天内每个匹配日别的
  日期各生成一批 VEVENT。
- UID 规则：``shuttle-{campus}-{daykind}-{date}-{time}@westlake_survival``，
  其中 ``{campus}`` / ``{daykind}`` 用枚举英文名（如 ``YUNGU`` / ``WEEKDAY``），
  保证 UID 为纯 ASCII、跨客户端稳定。

免责：日别仅按公历星期（周一~五=工作日，周六日=周末）推断，**不含法定假期 /
调休**；假期班车安排以学校邮件通知为准。方向语义见
:mod:`westlake_survival.transit.schedule`。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from westlake_survival.transit.schedule import (
    CHINA_TZ,
    TransitData,
    _calendar_day_kind,
)

PRODID = "-//westlake_survival//Transit Shuttle//CN"
CALENDAR_NAME = "西湖大学校巴时刻"

_DISCLAIMER = "法定假期 / 调休日班车安排以学校邮件通知为准；时刻为从始发校区开出。"


def _escape_text(value: str) -> str:
    """RFC 5545 TEXT 转义：反斜杠、分号、逗号、换行。"""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """按 RFC 5545 折行：每行不超过 75 个八位组，续行以空格开头。

    按字符边界切分（不切开多字节 UTF-8 字符），首行 ≤75 字节，
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


def _uid(campus_name: str, day_kind_name: str, day: date, time_str: str) -> str:
    stamp = day.strftime("%Y%m%d")
    clock = time_str.replace(":", "")
    return f"shuttle-{campus_name}-{day_kind_name}-{stamp}-{clock}@westlake_survival"


def transit_to_ical(
    weekdays_ahead: int = 14,
    *,
    data: TransitData | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> str:
    """生成未来 ``weekdays_ahead`` 天的班车 ``.ics`` 文本。

    Args:
        weekdays_ahead: 生成天数（含今天，从今天起算）。
        data: 数据源；``None`` 时用 :func:`westlake_survival.transit.transit`
            单例（惰性加载）。
        today: 起始日期（测试用）；``None`` 用 ``CHINA_TZ`` 当天。
        now: ``DTSTAMP`` 时刻（测试用）；``None`` 用当前 UTC 时间。

    Returns:
        完整的 VCALENDAR 字符串（CRLF 换行）。
    """
    if data is None:
        from westlake_survival.transit import transit

        data = transit()
    start_day = today or datetime.now(CHINA_TZ).date()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(CALENDAR_NAME)}",
    ]

    for offset in range(weekdays_ahead):
        day = start_day + timedelta(days=offset)
        kind = _calendar_day_kind(day)
        for tbl in data.tables:
            if tbl.day_kind != kind:
                continue
            for time_str in tbl.all_times():
                local = f"{day.strftime('%Y%m%d')}T{time_str.replace(':', '')}00"
                summary = f"校巴 {tbl.campus.value}始发 {time_str}"
                description = f"{tbl.direction_note} {_DISCLAIMER}".strip()
                lines.append("BEGIN:VEVENT")
                lines.append(f"UID:{_uid(tbl.campus.name, tbl.day_kind.name, day, time_str)}")
                lines.append(f"DTSTAMP:{stamp}")
                lines.append(f"DTSTART:{local}")
                lines.append(f"SUMMARY:{_escape_text(summary)}")
                lines.append(f"DESCRIPTION:{_escape_text(description)}")
                lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"