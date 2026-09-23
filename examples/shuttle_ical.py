"""导出校园班车时刻表为 iCalendar 文件。

用途
    把未来若干天的校巴时刻写成 ``shuttle.ics``，可直接导入
    Google Calendar / Apple 日历 / Outlook。

前置条件
    - 无认证；联网时从官网抓取最新时刻表，断网时回退到内置兜底数据。

产出
    当前工作目录下 ``shuttle.ics``（浮动本地时间，客户端按本地时区显示）。

运行::

    python examples/shuttle_ical.py          # 未来 14 天
    python examples/shuttle_ical.py 30       # 未来 30 天
"""

from __future__ import annotations

import sys
from pathlib import Path

from westlake_survival.transit import transit_to_ical


def main() -> int:
    days = 14
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"天数应为整数，得到 {sys.argv[1]!r}", file=sys.stderr)
            return 2

    destination = Path("shuttle.ics")
    try:
        text = transit_to_ical(days)
        destination.write_text(text, encoding="utf-8")
    except Exception as exc:  # 兜底：不让示例以堆栈收场
        print(f"导出班车 iCalendar 失败：{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1

    events = text.count("BEGIN:VEVENT")
    print(f"已写入 {destination.resolve()}")
    print(f"共 {events} 个班车事件（未来 {days} 天）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
