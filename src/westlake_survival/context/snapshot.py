"""每日快照（Context）：面向 AI 助手 / 学生的"此刻西湖"一屏速览。

这是整个库的 **Agent 入口**：AI 助手或学生只需一次调用即可拿到
"今天是第几周、最近有什么校历事件、下班车几点、天气如何、最近有哪些
作业截止"——所有信息聚合成一个对象，并可直接渲染成中文 markdown。

设计要点
========
- **三档信息量**（:class:`Level`）：

  ==========  ============================================  ==========
  Level       内容                                          目标耗时
  ==========  ============================================  ==========
  ``TERSE``   纯本地快算：日期 / 星期 / 学期 / 周次         <1ms
  ``NORMAL``  + 最近校历事件 + 最近班车                      <2s
  ``VERBOSE`` + 天气 + AQI + Canvas 作业截止                 <5s
  ==========  ============================================  ==========

- **优雅降级铁律**：任何一处 I/O（天气 / AQI / Canvas / 班车 / 校历网络）
  失败，对应字段置 ``None`` 并记 ``logging.warning``；构造 :class:`Context`
  与调用 :meth:`Context.to_dict` / :meth:`Context.to_str` **绝不抛异常**。
  班车数据有内置兜底，基本总可用。

- **惰性求值 + 实例级缓存**：各字段是 ``property``，首次访问才计算，结果
  缓存在实例上（用 ``object.__setattr__`` 写入私有槽，避免重复网络请求）。

用法::

    from westlake_survival.context import snapshot, Level

    ctx = snapshot()                 # 默认 NORMAL
    print(ctx.to_str())              # 中文 markdown 快照
    ctx.weather                      # 天气 dict（失败为 None）
    ctx.next_deadlines               # 最近 Canvas 作业

坐标与端点
==========
主坐标取西湖大学云谷校区附近（``LATITUDE`` / ``LONGITUDE``，可覆写）；
天气 / AQI 走 Open-Meteo 免 key 接口。数据时效性高，故不走 ETag 缓存。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any

from westlake_survival._net import http_session

__all__ = [
    "AQI_API",
    "CHINA_TZ",
    "Context",
    "LATITUDE",
    "LONGITUDE",
    "Level",
    "WMO_WEATHER_CN",
    "WEATHER_API",
    "aqi_grade",
    "snapshot",
]

logger = logging.getLogger(__name__)

#: 中国标准时间（东八区）。优先 zoneinfo，Windows 缺 tzdata 时退化为固定偏移。
try:  # pragma: no cover - 依赖环境
    from zoneinfo import ZoneInfo

    CHINA_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 依赖环境
    from datetime import timedelta, timezone

    CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

#: 西湖大学云谷校区附近坐标（Open-Meteo 实测可用）。
LATITUDE = 30.31
LONGITUDE = 120.07

#: Open-Meteo 天气预报接口（免 key）。
WEATHER_API = "https://api.open-meteo.com/v1/forecast"

#: Open-Meteo 空气质量接口（免 key）。
AQI_API = "https://air-quality-api.open-meteo.com/v1/air-quality"

#: HTTP 超时（秒）。天气接口响应很快，8s 足够。
TIMEOUT = 8.0

#: 中文星期名，索引 = ``date.weekday()``（0=周一）。
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: WMO 天气码 → 中文现象描述（见 Open-Meteo 文档的 WMO Weather interpretation codes）。
WMO_WEATHER_CN: dict[int, str] = {
    0: "晴",
    1: "少云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "毛毛雨",
    56: "冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "雷暴伴冰雹",
}


def wmo_text(code: int | None) -> str:
    """WMO 天气码转中文；未知码返回 ``"未知"``，``None`` 返回 ``"未知"``。"""
    if code is None:
        return "未知"
    return WMO_WEATHER_CN.get(int(code), "未知")


def aqi_grade(us_aqi: float | int | None) -> str:
    """US AQI 分级中文描述。

    0-50 优 / 51-100 良 / 101-150 轻度污染 / 151-200 中度污染 /
    201-300 重度污染 / >300 严重污染；``None`` → ``"未知"``。
    """
    if us_aqi is None:
        return "未知"
    value = float(us_aqi)
    if value <= 50:
        return "优"
    if value <= 100:
        return "良"
    if value <= 150:
        return "轻度污染"
    if value <= 200:
        return "中度污染"
    if value <= 300:
        return "重度污染"
    return "严重污染"


class Level(str, Enum):
    """快照信息量档位。"""

    TERSE = "terse"  # 纯本地快算
    NORMAL = "normal"  # + 校历事件 + 班车
    VERBOSE = "verbose"  # + 天气 + AQI + Canvas 截止


# --------------------------------------------------------------------------- #
# 数据抓取（各返回 None 表示失败，绝不抛）
# --------------------------------------------------------------------------- #
def fetch_weather(now: datetime | None = None) -> dict[str, Any] | None:
    """抓取实时天气 + 今明预报；失败返回 ``None``。

    返回结构::

        {
          "temperature": float, "humidity": int, "wind_speed": float,
          "weather_code": int, "text": str, "time": str,
          "daily": [{"date": str, "code": int, "text": str,
                     "tmax": float, "tmin": float, "precip_prob": int}, ...],
        }
    """
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max",
        "timezone": "Asia/Shanghai",
        "forecast_days": 3,
    }
    try:
        session = http_session()
        response = session.get(WEATHER_API, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        return _parse_weather(payload)
    except Exception as exc:  # noqa: BLE001 - 优雅降级，任何失败都置 None
        logger.warning("抓取天气失败（%s）：%s", exc.__class__.__name__, exc)
        return None


def _parse_weather(payload: dict[str, Any]) -> dict[str, Any]:
    """把 Open-Meteo 天气响应解析成扁平结构（纯函数，便于测试）。"""
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    code = current.get("weather_code")
    result: dict[str, Any] = {
        "temperature": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_speed": current.get("wind_speed_10m"),
        "weather_code": code,
        "text": wmo_text(code),
        "time": current.get("time"),
        "daily": [],
    }
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_probability_max") or []
    for idx, day in enumerate(dates):
        day_code = codes[idx] if idx < len(codes) else None
        result["daily"].append(
            {
                "date": day,
                "code": day_code,
                "text": wmo_text(day_code),
                "tmax": tmax[idx] if idx < len(tmax) else None,
                "tmin": tmin[idx] if idx < len(tmin) else None,
                "precip_prob": precip[idx] if idx < len(precip) else None,
            }
        )
    return result


def fetch_aqi(now: datetime | None = None) -> dict[str, Any] | None:
    """抓取实时空气质量；失败返回 ``None``。

    返回结构::

        {"pm10": float, "pm2_5": float, "us_aqi": int,
         "european_aqi": int, "grade": str}
    """
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "pm10,pm2_5,us_aqi,european_aqi",
        "timezone": "Asia/Shanghai",
    }
    try:
        session = http_session()
        response = session.get(AQI_API, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        return _parse_aqi(payload)
    except Exception as exc:  # noqa: BLE001 - 优雅降级
        logger.warning("抓取空气质量失败（%s）：%s", exc.__class__.__name__, exc)
        return None


def _parse_aqi(payload: dict[str, Any]) -> dict[str, Any]:
    """把 Open-Meteo 空气质量响应解析成扁平结构（纯函数）。"""
    current = payload.get("current") or {}
    us_aqi = current.get("us_aqi")
    return {
        "pm10": current.get("pm10"),
        "pm2_5": current.get("pm2_5"),
        "us_aqi": us_aqi,
        "european_aqi": current.get("european_aqi"),
        "grade": aqi_grade(us_aqi),
    }


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #
@dataclass
class Context:
    """每日快照。各字段惰性求值，结果缓存在实例上。

    Args:
        level: 信息量档位，见 :class:`Level`。
        now: 注入的当前时刻（测试用）；``None`` 用 ``CHINA_TZ`` 当前时间。
    """

    level: Level = Level.NORMAL
    now: datetime = field(default=None)  # type: ignore[assignment]

    #: 内部缓存（不参与 ``repr`` / 比较 / 序列化）。
    _cache: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.now is None:
            self.now = datetime.now(CHINA_TZ)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=CHINA_TZ)
        # 归一化 level（允许传字符串）。
        if not isinstance(self.level, Level):
            self.level = Level(self.level)

    # -- 惰性字段 ---------------------------------------------------------- #
    def _get(self, key: str, factory):
        """取缓存值；未命中时调用 *factory* 并缓存。

        即使 *factory* 抛异常也降级为 ``None``（记 warning），保证构造与
        序列化绝不因 I/O 失败而中断——这是"优雅降级铁律"的兜底实现。
        """
        if key not in self._cache:
            try:
                self._cache[key] = factory()
            except Exception as exc:  # noqa: BLE001 - 优雅降级兜底
                logger.warning("计算 %s 失败（%s）：%s", key, exc.__class__.__name__, exc)
                self._cache[key] = None
        return self._cache[key]

    @property
    def date(self) -> date:
        """今天的日期。"""
        return self._get("date", lambda: self.now.date())

    @property
    def weekday_cn(self) -> str:
        """中文星期名，如 ``"周二"``。"""
        return self._get("weekday_cn", lambda: _WEEKDAY_CN[self.now.weekday()])

    @property
    def semester_name(self) -> str | None:
        """当前学期名，如 ``"2026年秋季"``；不在教学期返回 ``None``。"""
        return self._get("semester_name", self._compute_semester_name)

    @property
    def week_number(self) -> int | None:
        """当前教学周次；不在教学期返回 ``None``。"""
        return self._get("week_number", self._compute_week_number)

    @property
    def next_event(self):
        """最近的校历事件（:class:`~westlake_survival.calendar.CalendarEvent`）；失败返回 ``None``。"""
        if self.level is Level.TERSE:
            return None
        return self._get("next_event", self._compute_next_event)

    @property
    def next_shuttles(self) -> list[tuple[Any, str]] | None:
        """下一批班车 ``[(ShuttleTable, "HH:MM"), ...]``；失败返回 ``None``。"""
        if self.level is Level.TERSE:
            return None
        return self._get("next_shuttles", self._compute_next_shuttles)

    @property
    def weather(self) -> dict[str, Any] | None:
        """实时天气 dict（结构见 :func:`fetch_weather`）；失败返回 ``None``。"""
        if self.level is not Level.VERBOSE:
            return None
        return self._get("weather", lambda: fetch_weather(self.now))

    @property
    def aqi(self) -> dict[str, Any] | None:
        """实时空气质量 dict（结构见 :func:`fetch_aqi`）；失败返回 ``None``。"""
        if self.level is not Level.VERBOSE:
            return None
        return self._get("aqi", lambda: fetch_aqi(self.now))

    @property
    def next_deadlines(self) -> list[Any] | None:
        """最近的 Canvas 作业截止列表；无 token / 失败返回 ``None``。"""
        if self.level is not Level.VERBOSE:
            return None
        return self._get("next_deadlines", self._compute_next_deadlines)

    # -- 计算实现 ---------------------------------------------------------- #
    def _load_calendar(self):
        from westlake_survival.calendar import AcademicCalendar

        return AcademicCalendar.load()

    def _compute_semester_name(self) -> str | None:
        try:
            calendar = self._load_calendar()
            semester = calendar.current(self.date)
            return semester.name if semester is not None else None
        except Exception as exc:  # noqa: BLE001 - 优雅降级
            logger.warning("读取学期失败（%s）：%s", exc.__class__.__name__, exc)
            return None

    def _compute_week_number(self) -> int | None:
        try:
            calendar = self._load_calendar()
            result = calendar.week_of(self.date)
            return result[1] if result is not None else None
        except Exception as exc:  # noqa: BLE001 - 优雅降级
            logger.warning("读取教学周次失败（%s）：%s", exc.__class__.__name__, exc)
            return None

    def _compute_next_event(self):
        try:
            calendar = self._load_calendar()
            return calendar.next_event(self.date)
        except Exception as exc:  # noqa: BLE001 - 优雅降级
            logger.warning("读取最近校历事件失败（%s）：%s", exc.__class__.__name__, exc)
            return None

    def _compute_next_shuttles(self) -> list[tuple[Any, str]] | None:
        try:
            from westlake_survival.transit import transit

            data = transit()
            return data.next_departures(now=self.now, limit=3)
        except Exception as exc:  # noqa: BLE001 - 优雅降级
            logger.warning("读取班车时刻失败（%s）：%s", exc.__class__.__name__, exc)
            return None

    def _compute_next_deadlines(self) -> list[Any] | None:
        try:
            from westlake_survival.canvas import upcoming_deadlines

            return upcoming_deadlines(limit=5)
        except Exception as exc:  # noqa: BLE001 - 优雅降级（无 token 时 AuthError）
            logger.warning("读取 Canvas 作业截止失败（%s）：%s", exc.__class__.__name__, exc)
            return None

    # -- 序列化 ------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        """转成 JSON 可序列化的 dict（datetime→ISO、date→ISO、枚举→值）。

        任何字段取值失败都不会抛异常（各 property 已降级为 ``None``）。
        """
        result: dict[str, Any] = {
            "level": self.level.value if isinstance(self.level, Level) else str(self.level),
            "now": _iso(self.now),
            "date": _iso(self.date),
            "weekday_cn": self.weekday_cn,
            "semester_name": self.semester_name,
            "week_number": self.week_number,
            "next_event": _event_to_dict(self.next_event),
            "next_shuttles": _shuttles_to_dict(self.next_shuttles),
            "weather": _plain(self.weather),
            "aqi": _plain(self.aqi),
            "next_deadlines": _deadlines_to_dict(self.next_deadlines),
        }
        return result

    def to_str(self) -> str:
        """渲染成中文 markdown 快照（供 AI 助手直接喂给用户）。"""
        header = f"西湖大学 · {self.date.isoformat()} {self.weekday_cn}"
        if self.semester_name:
            header += f" · {self.semester_name}"
            if self.week_number is not None:
                header += f" 第{self.week_number}周"
        lines = [f"# {header}", ""]

        # 📅 最近校历事件
        lines.append("## 📅 最近校历事件")
        event = self.next_event
        if event is None:
            lines.append("（暂无）")
        else:
            span = event.start.isoformat()
            if event.end is not None and event.end != event.start:
                span += f" ~ {event.end.isoformat()}"
            lines.append(f"- {event.title}（{span}）")
        lines.append("")

        # 🚌 下班车
        lines.append("## 🚌 下班车")
        # 复用 _shuttles_to_dict 的防御性转换：契约外结构只跳过违约项，
        # 渲染路径同样绝不因下游返回畸形而抛异常。
        shuttle_items = _shuttles_to_dict(self.next_shuttles)
        if not shuttle_items:
            lines.append("（暂无）")
        else:
            for item in shuttle_items:
                lines.append(f"- {item['time']} 从 {item['campus']} 开出")
        lines.append("")

        # 🌤️ 天气
        lines.append("## 🌤️ 天气")
        lines.append(self._weather_lines())
        lines.append("")

        # 📌 最近截止
        lines.append("## 📌 最近截止")
        lines.append(self._deadline_lines())
        return "\n".join(lines)

    def _weather_lines(self) -> str:
        weather = self.weather
        aqi = self.aqi
        if weather is None and aqi is None:
            return "（暂无）"
        out: list[str] = []
        if weather is not None:
            parts = [f"当前 {_fmt_num(weather.get('temperature'))}℃"]
            if weather.get("text"):
                parts.append(str(weather["text"]))
            humidity = weather.get("humidity")
            if humidity is not None:
                parts.append(f"湿度 {humidity}%")
            wind = weather.get("wind_speed")
            if wind is not None:
                parts.append(f"风速 {_fmt_num(wind)} km/h")
            out.append("- " + " · ".join(parts))
            daily = weather.get("daily") or []
            for idx, day in enumerate(daily):
                label = "今日" if idx == 0 else ("明日" if idx == 1 else str(day.get("date")))
                seg = (
                    f"{label} {day.get('text', '未知')} "
                    f"{_fmt_num(day.get('tmin'))}~{_fmt_num(day.get('tmax'))}℃"
                )
                if day.get("precip_prob") is not None:
                    seg += f" 降水概率 {day['precip_prob']}%"
                out.append(f"  - {seg}")
        if aqi is not None:
            seg = f"空气质量 {aqi.get('grade', '未知')}"
            if aqi.get("us_aqi") is not None:
                seg += f"（US AQI {aqi['us_aqi']}）"
            out.append("- " + seg)
        return "\n".join(out)

    def _deadline_lines(self) -> str:
        try:
            deadlines = self.next_deadlines
            if not deadlines:
                return "（暂无）"
            out: list[str] = []
            for assignment in deadlines:
                due = getattr(assignment, "due_at", None)
                name = getattr(assignment, "name", None) or "（未命名作业）"
                when = _due_text(due, self.now)
                out.append(f"- {name}（{when}）")
            return "\n".join(out)
        except Exception as exc:  # noqa: BLE001 - 渲染路径绝不抛
            logger.warning("渲染作业截止失败（%s）：%s", exc.__class__.__name__, exc)
            return "（暂无）"


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _fmt_num(value: Any) -> str:
    """数值格式化：整数省略小数点，``None`` → ``"—"``。"""
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return str(int(num))
    return f"{num:.1f}"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _plain(value: Any) -> Any:
    """把嵌套结构里的 datetime/date 递归转成 ISO 字符串。"""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _event_to_dict(event: Any) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "title": getattr(event, "title", None),
        "start": _iso(getattr(event, "start", None)),
        "end": _iso(getattr(event, "end", None)),
    }


def _shuttles_to_dict(shuttles: Any) -> list[dict[str, Any]] | None:
    """把 ``transit.next_departures`` 的 ``[(table, "HH:MM"), ...]`` 转成 dict 列表。

    下游返回契约外结构（非二元组、``None`` 元素等）时**绝不抛异常**：违约的
    单项跳过，整体不可迭代时返回 ``None``——与 :meth:`Context._get` 同款兜底，
    保证 ``to_dict`` 的"绝不抛异常"铁律。
    """
    if shuttles is None:
        return None
    out: list[dict[str, Any]] = []
    try:
        for item in shuttles:
            try:
                table, ts = item
            except (TypeError, ValueError):
                # 契约外结构（三元组 / 单值 / None 元素）跳过该项。
                logger.warning("班车条目结构异常，跳过：%r", item)
                continue
            campus = getattr(table, "campus", None)
            day_kind = getattr(table, "day_kind", None)
            out.append(
                {
                    "time": ts,
                    "campus": getattr(campus, "value", campus),
                    "day_kind": getattr(day_kind, "value", day_kind),
                }
            )
    except Exception as exc:  # noqa: BLE001 - 优雅降级兜底
        logger.warning("班车列表不可迭代（%s）：%s", exc.__class__.__name__, exc)
        return None
    return out


def _deadlines_to_dict(deadlines: Any) -> list[dict[str, Any]] | None:
    """把 ``canvas.upcoming_deadlines`` 的返回值转成 dict 列表。

    下游返回契约外结构（不可迭代等）时返回 ``None`` 而非抛异常——与
    :meth:`Context._get` 同款兜底，保证 ``to_dict`` 绝不抛。
    """
    if deadlines is None:
        return None
    out: list[dict[str, Any]] = []
    try:
        for assignment in deadlines:
            out.append(
                {
                    "name": getattr(assignment, "name", None),
                    "due_at": _iso(getattr(assignment, "due_at", None)),
                    "course_id": getattr(assignment, "course_id", None),
                    "html_url": getattr(assignment, "html_url", None),
                }
            )
    except Exception as exc:  # noqa: BLE001 - 优雅降级兜底
        logger.warning("作业列表结构异常（%s）：%s", exc.__class__.__name__, exc)
        return None
    return out


def _due_text(due: datetime | None, now: datetime) -> str:
    """把截止时刻渲染成"MM-DD HH:MM"并附剩余天数。"""
    if due is None:
        return "无截止日期"
    text = due.strftime("%m-%d %H:%M")
    try:
        delta_days = (due.date() - now.date()).days
    except Exception:  # noqa: BLE001
        return text
    if delta_days < 0:
        text += "（已过期）"
    elif delta_days == 0:
        text += "（今天）"
    elif delta_days == 1:
        text += "（明天）"
    else:
        text += f"（{delta_days}天后）"
    return text


def snapshot(level: Level = Level.NORMAL, now: datetime | None = None) -> Context:
    """便捷函数：构造一个 :class:`Context` 快照。

    Args:
        level: 信息量档位。
        now: 注入的当前时刻（测试用）。
    """
    return Context(level=level, now=now)