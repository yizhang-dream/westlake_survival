"""校园巴士时刻表：数据模型、解析与加载。

数据来源
========
西湖大学官网「住宿餐饮」页面
(https://www.westlake.edu.cn/campus_life/housing_dining/) 的 Vue 组件数据里，
内嵌了一段未加引号的 JS 对象数组，其中 ``//交通方式`` 注释块内即班车时刻表。
页面是 Vue SPA，但数据直接内嵌在返回的 HTML 中，因此可离线解析，无需执行 JS。
专门的 ``workday_shuttle_bus_schedule/`` 等子页是空壳，数据仍来自本页。

实测结构（2026-09-22，见 ``parse_schedule`` 的健壮正则）::

    //交通方式
    {
      keyword: "交通方式",
      type: "1",
      notice: "<div ...>点击查看班车实时信息</a>，法定假期 / 调休日班车安排，以学校邮件通知为准。</div>",
      list: [
        {
          title:"工作日班车时间表", titleEn:'Workday Shuttle Bus Schedule',
          listItem:[
            { titleCampus:'云谷', morning:[...], noon:[...], night:[...] },
            { titleCampus:'云栖', morning:[...], noon:[...], night:[...] },
            { titleCampus:'铜鉴湖', otherCar1:[...], otherCar2:[...] },
          ]
        },
        { title:"周末班车时间表", ... },
      ]
    }

方向语义坑（重要）
==================
- 时刻按 **始发校区** 分组：``titleCampus:'云谷'`` 下的时刻表示「从云谷开出」，
  而不是「到达云谷」。方向为 **往返 云谷 ↔ 云栖**（铜鉴湖为园区专线）。
- 铜鉴湖没有 ``morning/noon/night``，而是 ``otherCar1`` / ``otherCar2`` 两组车次；
  本模块把 ``otherCar1`` 映射到 ``morning``、``otherCar2`` 映射到 ``noon``，
  ``night`` 留空，并在 ``direction_note`` 中说明，以免丢失两组语义。
- 法定假期 / 调休日班车安排以学校邮件通知为准，本模块只反映官网公布的工作日/周末表。

实时信息（本期不做）
====================
官网 notice 指向第三方 H5 实时班车页
(https://security.zjwsvip.com/#/h5shuttleRoute/1906876984879099905)，为 Vue SPA +
``/prod-api/`` 后端，稳定性无保障，本期不实现，仅在此留线索。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum

from westlake_survival._cache import cache_path, http_get_with_etag
from westlake_survival.exceptions import ParseError

#: 中国标准时间（固定 UTC+8；不用 zoneinfo 以避开 Windows 缺 tzdata 的问题）。
CHINA_TZ = timezone(timedelta(hours=8), name="CST")

#: 时刻表页面 URL。
HOUSING_DINING_URL = "https://www.westlake.edu.cn/campus_life/housing_dining/"

#: 缓存名（相对 cache 目录）。
CACHE_NAME = "transit/housing_dining.html"


class Campus(str, Enum):
    """校区。值即官网展示名，可直接用于展示。"""

    YUNGU = "云谷"
    YUNQI = "云栖"
    TONGJIANHU = "铜鉴湖"


class DayKind(str, Enum):
    """日别类型。值即官网分组名。"""

    WEEKDAY = "工作日"
    WEEKEND = "周末"


#: 各校区方向说明（写入 ShuttleTable.direction_note）。
_DIRECTION_NOTES = {
    Campus.YUNGU: "始发云谷，往返 云谷 ↔ 云栖（时刻为从云谷开出）",
    Campus.YUNQI: "始发云栖，往返 云谷 ↔ 云栖（时刻为从云栖开出）",
    Campus.TONGJIANHU: "铜鉴湖园区专线，往返 铜鉴湖 ↔ 云谷/云栖；"
    "otherCar1→morning、otherCar2→noon 两组车次",
}


@dataclass(frozen=True)
class ShuttleTable:
    """某校区、某日别的一张班车时刻表。

    注意：``morning`` / ``noon`` / ``night`` 只是官网的时段分组名，
    **时刻均为从本表 ``campus`` 开出的时间**，方向见 ``direction_note``。
    """

    campus: Campus
    day_kind: DayKind
    direction_note: str = ""
    morning: tuple[str, ...] = ()
    noon: tuple[str, ...] = ()
    night: tuple[str, ...] = ()

    def all_times(self) -> list[str]:
        """返回本表全部时刻（``HH:MM``，未排序）。"""
        return [*self.morning, *self.noon, *self.night]


@dataclass
class TransitData:
    """整份班车数据：若干张 :class:`ShuttleTable`。"""

    tables: list[ShuttleTable] = field(default_factory=list)

    def table(self, campus: Campus, day_kind: DayKind) -> ShuttleTable | None:
        """按 (校区, 日别) 取表；不存在返回 ``None``。"""
        for tbl in self.tables:
            if tbl.campus == campus and tbl.day_kind == day_kind:
                return tbl
        return None

    def next_departures(
        self,
        after: time | None = None,
        campus: Campus | None = None,
        day_kind: DayKind | None = None,
        limit: int = 3,
        now: datetime | None = None,
    ) -> list[tuple[ShuttleTable, str]]:
        """返回 ``after`` 之后的下一批发车时刻。

        Args:
            after: 起始时刻（当日）；``None`` 用 ``now`` 的当前时间。
            campus: 只保留该校区；``None`` 表示全部。
            day_kind: 只保留该日别；``None`` 表示按日历（周一~五=工作日，
                周六日=周末）逐日推断。
            limit: 最多返回条数。
            now: 注入的当前时刻（测试用）；``None`` 用 ``CHINA_TZ`` 当前时间。

        Returns:
            ``(ShuttleTable, "HH:MM")`` 列表，按 (日期偏移, 时刻) 升序；
            当天已无车次时顺延到之后首个匹配日期的首班。

        局限：日别仅按公历星期推断，**不含法定假期 / 调休**——假期安排以
        学校邮件通知为准。``after`` 只过滤起始当日；起始当日不匹配
        ``day_kind`` 时会顺延到之后首个匹配日期，并给出该日全部车次。
        """
        moment = now or datetime.now(CHINA_TZ)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=CHINA_TZ)
        base_date = moment.date()
        after_time = after if after is not None else moment.timetz().replace(tzinfo=None)
        after_str = after_time.strftime("%H:%M")

        results: list[tuple[ShuttleTable, str]] = []
        for offset in range(0, 8):
            day = base_date + timedelta(days=offset)
            kind = day_kind or _calendar_day_kind(day)
            if day_kind is not None and _calendar_day_kind(day) != day_kind:
                # 显式指定日别时，跳过日历上不匹配的日期。
                continue
            candidates: list[tuple[str, ShuttleTable]] = []
            for tbl in self.tables:
                if tbl.day_kind != kind:
                    continue
                if campus is not None and tbl.campus != campus:
                    continue
                for ts in tbl.all_times():
                    if offset == 0 and ts <= after_str:
                        continue
                    candidates.append((ts, tbl))
            candidates.sort(key=lambda item: item[0])
            results.extend((tbl, ts) for ts, tbl in candidates)
            if len(results) >= limit:
                break
        return results[:limit]

    @classmethod
    def load(cls, refresh: bool = False) -> "TransitData":
        """从官网加载并解析；网络或解析失败时回退到内置 :data:`FALLBACK_TABLES`。"""
        if refresh:
            try:
                cache_path(CACHE_NAME).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            body, _etag = http_get_with_etag(HOUSING_DINING_URL, cache_name=CACHE_NAME)
            return parse_schedule(body)
        except Exception:
            # 网络不可达 / 页面结构变化 / 解析失败：一律回退到内置数据。
            return cls(tables=list(FALLBACK_TABLES))


def _calendar_day_kind(day: date) -> DayKind:
    """按公历星期判断日别（周一~五=工作日，周六日=周末）。"""
    return DayKind.WEEKEND if day.weekday() >= 5 else DayKind.WEEKDAY


def _repair_encoding(text: str) -> str:
    """修正 ``requests`` 把 UTF-8 页面按 latin-1 解码造成的乱码。

    共享层 ``http_get_with_etag`` 返回 ``response.text``；当服务器未声明
    charset 时 ``requests`` 会按 ISO-8859-1 解码，中文变乱码。这里尝试
    反解回原始字节再按 UTF-8 解码；若文本本身已是正常 Unicode，则原样返回。
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _extract_balanced(text: str, start: int) -> str:
    """从 ``text[start]``（须为 ``[``）起提取配对的方括号子串（跳过字符串内括号）。"""
    depth = 0
    idx = start
    quote: str | None = None
    while idx < len(text):
        char = text[idx]
        if quote is not None:
            if char == "\\":
                idx += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
        idx += 1
    raise ParseError("班车数据块括号不配对")


_ARRAY_ITEM_RE = re.compile(r"['\"]([^'\"]*)['\"]")
_TITLE_RE = re.compile(r"title\s*:\s*['\"]([^'\"]+)['\"]")
_CAMPUS_RE = re.compile(r"titleCampus\s*:\s*['\"]([^'\"]+)['\"]")


def _find_shuttle_list(html: str) -> str:
    """定位 ``keyword: "交通方式"`` 后的 ``list: [...]`` 并返回其方括号子串。"""
    keyword = re.search(r"keyword\s*:\s*['\"]交通方式['\"]", html)
    if keyword is None:
        raise ParseError("未找到「交通方式」数据块")
    list_kw = re.search(r"list\s*:\s*\[", html[keyword.end() :])
    if list_kw is None:
        raise ParseError("「交通方式」块内未找到 list")
    bracket = keyword.end() + list_kw.end() - 1  # 指向 list 的 '['
    return _extract_balanced(html, bracket)


def _extract_array(block: str, key: str) -> tuple[str, ...]:
    """从一段 JS 文本里取 ``key: ['..','..']`` 的字符串数组。"""
    match = re.search(rf"{key}\s*:\s*\[([^\]]*)\]", block)
    if match is None:
        return ()
    return tuple(_ARRAY_ITEM_RE.findall(match.group(1)))


def _parse_group(group: str, day_kind: DayKind) -> list[ShuttleTable]:
    """解析一个日别分组（工作日/周末）内的各校区条目。"""
    campus_matches = list(_CAMPUS_RE.finditer(group))
    tables: list[ShuttleTable] = []
    for i, match in enumerate(campus_matches):
        end = campus_matches[i + 1].start() if i + 1 < len(campus_matches) else len(group)
        block = group[match.start() : end]
        name = match.group(1)
        try:
            campus = Campus(name)
        except ValueError:
            continue  # 官网新增未知校区：跳过而不报错。
        if campus is Campus.TONGJIANHU:
            morning = _extract_array(block, "otherCar1")
            noon = _extract_array(block, "otherCar2")
            night: tuple[str, ...] = ()
        else:
            morning = _extract_array(block, "morning")
            noon = _extract_array(block, "noon")
            night = _extract_array(block, "night")
        tables.append(
            ShuttleTable(
                campus=campus,
                day_kind=day_kind,
                direction_note=_DIRECTION_NOTES.get(campus, ""),
                morning=morning,
                noon=noon,
                night=night,
            )
        )
    return tables


def parse_schedule(html: str) -> TransitData:
    """解析官网页面 HTML，返回 :class:`TransitData`。

    对编码乱码、未加引号的 JS 键、单/双引号混用、尾随逗号都做了容错。
    页面结构不符时抛 :class:`~westlake_survival.exceptions.ParseError`。
    """
    text = _repair_encoding(html)
    list_block = _find_shuttle_list(text)
    title_matches = list(_TITLE_RE.finditer(list_block))
    tables: list[ShuttleTable] = []
    for i, match in enumerate(title_matches):
        end = title_matches[i + 1].start() if i + 1 < len(title_matches) else len(list_block)
        title = match.group(1)
        if "工作日" in title:
            day_kind = DayKind.WEEKDAY
        elif "周末" in title:
            day_kind = DayKind.WEEKEND
        else:
            continue
        tables.extend(_parse_group(list_block[match.start() : end], day_kind))
    if not tables:
        raise ParseError("未能从页面解析出任何班车时刻表")
    return TransitData(tables=tables)


def _fallback_tables() -> tuple[ShuttleTable, ...]:
    """内置兜底数据（2026-09-22 实测官网，与页面一致）。"""

    def tbl(campus: Campus, day_kind: DayKind, morning, noon, night) -> ShuttleTable:
        return ShuttleTable(
            campus=campus,
            day_kind=day_kind,
            direction_note=_DIRECTION_NOTES[campus],
            morning=tuple(morning),
            noon=tuple(noon),
            night=tuple(night),
        )

    return (
        tbl(
            Campus.YUNGU,
            DayKind.WEEKDAY,
            ("07:10", "08:40", "09:45", "11:00"),
            ("12:30", "13:00", "14:00", "15:30", "17:45"),
            ("18:30", "19:45", "21:00", "21:15"),
        ),
        tbl(
            Campus.YUNQI,
            DayKind.WEEKDAY,
            ("06:45", "07:10", "08:40", "09:30", "11:00"),
            ("12:30", "14:00", "15:15", "17:00", "17:45"),
            ("18:30", "19:45", "21:00"),
        ),
        tbl(
            Campus.TONGJIANHU,
            DayKind.WEEKDAY,
            (
                "06:35", "07:00", "08:30", "09:20", "10:50", "12:20", "13:50",
                "15:05", "16:50", "17:35", "18:20", "19:35", "20:50",
            ),
            (
                "08:20", "09:50", "10:45", "12:00", "13:30", "14:00", "15:00",
                "16:30", "18:50", "19:30", "20:40", "22:00", "22:10",
            ),
            (),
        ),
        tbl(
            Campus.YUNGU,
            DayKind.WEEKEND,
            ("08:00", "09:00"),
            ("13:00", "15:00", "17:00"),
            ("20:00",),
        ),
        tbl(
            Campus.YUNQI,
            DayKind.WEEKEND,
            ("09:10", "10:10"),
            ("14:10", "16:10", "18:10"),
            ("21:10",),
        ),
        tbl(
            Campus.TONGJIANHU,
            DayKind.WEEKEND,
            ("09:00", "10:00", "14:00", "16:00", "18:00", "21:00"),
            ("08:55", "09:55", "13:55", "15:55", "17:55", "20:55"),
            (),
        ),
    )


#: 网络不可达 / 解析失败时的内置兜底数据。
FALLBACK_TABLES: tuple[ShuttleTable, ...] = _fallback_tables()