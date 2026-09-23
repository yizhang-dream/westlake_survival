"""每日快照（context）子模块：面向 AI 助手 / 学生的"此刻西湖"入口。

公开 API::

    from westlake_survival.context import Context, Level, snapshot

    ctx = snapshot()                    # 默认 NORMAL 档
    print(ctx.to_str())                 # 中文 markdown 快照
    ctx.to_dict()                       # JSON 可序列化 dict

    snapshot(Level.TERSE)               # 纯本地快算（日期/周次/学期）
    snapshot(Level.VERBOSE)             # + 天气 + AQI + Canvas 截止

所有 I/O 失败均优雅降级为 ``None``，构造与序列化绝不抛异常。
"""

from __future__ import annotations

from westlake_survival.context.snapshot import (
    AQI_API,
    CHINA_TZ,
    LATITUDE,
    LONGITUDE,
    WEATHER_API,
    WMO_WEATHER_CN,
    Context,
    Level,
    aqi_grade,
    fetch_aqi,
    fetch_weather,
    snapshot,
    wmo_text,
)

__all__ = [
    "AQI_API",
    "CHINA_TZ",
    "LATITUDE",
    "LONGITUDE",
    "WEATHER_API",
    "WMO_WEATHER_CN",
    "Context",
    "Level",
    "aqi_grade",
    "fetch_aqi",
    "fetch_weather",
    "snapshot",
    "wmo_text",
]