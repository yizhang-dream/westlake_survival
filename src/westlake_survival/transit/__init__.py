"""西湖大学校园巴士（transit）模块。

公开 API::

    from westlake_survival.transit import transit, Campus, DayKind

    data = transit()                                   # 惰性加载 + 缓存
    data.table(Campus.YUNGU, DayKind.WEEKDAY)          # 单张表
    data.next_departures(campus=Campus.YUNGU)          # 下一批发车

    from westlake_survival.transit import transit_to_ical
    open("shuttle.ics", "w", encoding="utf-8").write(transit_to_ical())

数据来自官网「住宿餐饮」页面内嵌的 ``//交通方式`` JS 块；网络不可达时回退到
内置兜底数据。方向语义坑与假期免责说明见
:mod:`westlake_survival.transit.schedule`。
"""

from __future__ import annotations

from westlake_survival.transit.ical import transit_to_ical
from westlake_survival.transit.schedule import (
    CACHE_NAME,
    CHINA_TZ,
    FALLBACK_TABLES,
    HOUSING_DINING_URL,
    Campus,
    DayKind,
    ShuttleTable,
    TransitData,
    parse_schedule,
)

__all__ = [
    "Campus",
    "DayKind",
    "ShuttleTable",
    "TransitData",
    "parse_schedule",
    "transit",
    "transit_to_ical",
    "CHINA_TZ",
    "FALLBACK_TABLES",
    "CACHE_NAME",
    "HOUSING_DINING_URL",
]

_instance: TransitData | None = None


def transit(refresh: bool = False) -> TransitData:
    """返回进程内单例 :class:`TransitData`（惰性加载）。

    Args:
        refresh: 为 ``True`` 时强制重新从官网加载。
    """
    global _instance
    if _instance is None or refresh:
        _instance = TransitData.load(refresh=refresh)
    return _instance