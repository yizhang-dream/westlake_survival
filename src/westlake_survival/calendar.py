"""校历（Academic Calendar）解析与查询。

数据源是学校校历主页
``https://www.westlake.edu.cn/academics/academic_calendar/``。
该页是一个 Vue 单页应用，真正可用的数据内嵌在页面 HTML 的 ``<script>``
里的一段 ``new calendar("#app", { ... })`` 调用中：

* ``seasonList``：学期名数组，例如 ``["2026年春季", "2026年秋季"]``；
* ``contentList``：与 ``seasonList`` 一一对应的二维数组，每个子数组是一
  个学期的事件列表，每个事件形如 ``{title, time, endtime}``，日期格式为
  ``YYYY-MM-DD``（历史数据中亦见 ``YYYY/MM/DD``，解析两种都支持）。

子路径（如 ``.../2026Fall/``）返回 500 或空壳，因此只抓主页。

设计目标：把校历变成可编程查询的对象——给定日期查第几周、是否假日、
是否教学日、最近的事件等；网络不可用时用内置常量兜底。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from westlake_survival._cache import http_get_with_etag
from westlake_survival.exceptions import ParseError

__all__ = [
    "CHINA_TZ",
    "CalendarEvent",
    "Semester",
    "AcademicCalendar",
    "load",
    "parse_calendar",
    "FALLBACK_DATA",
    "CALENDAR_URL",
    "CACHE_NAME",
]

logger = logging.getLogger(__name__)

#: 中国标准时间（东八区）。
#:
#: 优先使用 :class:`zoneinfo.ZoneInfo`；Windows 上若缺少 ``tzdata`` 包
#: （Anaconda/标准库均不自带时区库），退化为固定 UTC+8 偏移——上海自 1991 年
#: 起不再使用夏令时，两者等价。
try:
    CHINA_TZ = ZoneInfo("Asia/Shanghai")
except (ZoneInfoNotFoundError, KeyError, ValueError):  # pragma: no cover - 依赖环境
    CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

#: 校历主页（唯一可抓取的页面）。
CALENDAR_URL = "https://www.westlake.edu.cn/academics/academic_calendar/"

#: ETag 缓存文件名（相对缓存目录）。
CACHE_NAME = "calendar/academic_calendar.html"

#: 日期字面量：``2026-08-31`` 或 ``2026/08/31``。
_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")

#: 调休补班日：标题中的 ``9月20日补上`` / ``6月22-23日补上`` 之类。
_MAKEUP_RE = re.compile(r"(\d{1,2})月(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*日\s*补")


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class CalendarEvent:
    """校历上的一个条目。

    ``end`` 为 ``None`` 表示单日事件（原始数据的 ``endtime`` 为空或等于
    ``time``）。``raw`` 保留原始 ``{title, time, endtime}`` 字符串，便于排查。
    """

    title: str
    start: date
    end: date | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_single_day(self) -> bool:
        return self.end is None

    @property
    def last_day(self) -> date:
        """事件覆盖的最后一天（单日事件即 ``start``）。"""
        return self.end or self.start

    def covers(self, d: date) -> bool:
        """``d`` 是否落在事件区间内（含端点）。"""
        return self.start <= d <= self.last_day


@dataclass
class Semester:
    """一个学期：课程开始日、课程结束日与全部校历事件。"""

    name: str
    start: date
    end: date
    events: list[CalendarEvent] = field(default_factory=list)

    # -- 周次换算 ---------------------------------------------------------- #
    def _week1_monday(self) -> date:
        """第 1 周（含 ``start`` 的那一周）的周一。"""
        return self.start - timedelta(days=self.start.weekday())

    @property
    def last_day(self) -> date:
        """学期覆盖的最后一天（学期末边界）。

        取课程结束日 ``end`` 与全部事件 ``last_day`` 的最大值，因此**包含
        考试周**等安排在课程结束之后的事件。用于 :meth:`week_of`、
        :meth:`AcademicCalendar.semester_for` 等的范围判定；
        :meth:`teaching_weeks` 仍只按 ``start``..``end`` 折算教学周数。
        """
        return max(self.end, *(e.last_day for e in self.events))

    def week_of(self, d: date) -> int | None:
        """``d`` 属于第几教学周；超出学期范围返回 ``None``。

        第 1 周 = 含课程开始日的那一周（以周一为界）。范围是
        ``start``..:attr:`last_day`（含学期末边界），因此**考试周内返回延续的
        教学周次**（例如第 18 周），而不是 ``None``。
        """
        if d < self.start or d > self.last_day:
            return None
        return (d - self._week1_monday()).days // 7 + 1

    def date_of(self, week: int, weekday: int) -> date:
        """返回第 ``week`` 周、``weekday``（1=周一 … 7=周日）对应的日期。"""
        if week < 1:
            raise ValueError(f"week 必须 >= 1，得到 {week!r}")
        if not 1 <= weekday <= 7:
            raise ValueError(f"weekday 必须在 1..7（1=周一），得到 {weekday!r}")
        return self._week1_monday() + timedelta(weeks=week - 1, days=weekday - 1)

    def teaching_weeks(self) -> int:
        """总教学周数（按 ``start``..``end`` 折算）。"""
        return (self.end - self._week1_monday()).days // 7 + 1

    # -- 假日 / 教学日 ----------------------------------------------------- #
    def makeup_days(self) -> set[date]:
        """从含"补"的事件标题里解析出的调休补班日。

        例：``"中秋节放假(9月20日补上9月25日的课）"`` → ``{2026-09-20}``。
        标题解析失败（无匹配）时返回空集——即保守地不认为任何周末是补班日。
        """
        days: set[date] = set()
        for event in self.events:
            if "补" not in event.title:
                continue
            year = event.start.year
            for m in _MAKEUP_RE.finditer(event.title):
                month = int(m.group(1))
                first = int(m.group(2))
                last = int(m.group(3)) if m.group(3) else first
                for day in range(first, last + 1):
                    try:
                        days.add(date(year, month, day))
                    except ValueError:  # 非法日期，忽略
                        continue
        return days

    def holiday_events(self) -> list[CalendarEvent]:
        """标题含"放假"的事件。"""
        return [e for e in self.events if "放假" in e.title]

    def exams(self) -> list[CalendarEvent]:
        """标题含"考试"的事件（如"期末考试周"）。"""
        return [e for e in self.events if "考试" in e.title]

    def is_holiday(self, d: date) -> bool:
        """``d`` 是否是假日：落在含"放假"的事件区间内，且不是调休补班日。"""
        makeup = self.makeup_days()
        for event in self.holiday_events():
            if event.covers(d) and d not in makeup:
                return True
        return False

    def is_teaching_day(self, d: date) -> bool:
        """``d`` 是否是教学日。

        教学日 = 在教学范围内、非假日、非周末；调休补班日（标题解析出的
        "补上"日）即使是周末也算上课。标题解析失败时保守返回 ``False``。
        """
        if d < self.start or d > self.end:
            return False
        if self.is_holiday(d):
            return False
        if d in self.makeup_days():
            return True
        return d.weekday() < 5


@dataclass
class AcademicCalendar:
    """整份校历：若干学期。"""

    semesters: list[Semester] = field(default_factory=list)

    # -- 查询 -------------------------------------------------------------- #
    def semester_for(self, d: date) -> Semester | None:
        """返回覆盖 ``d`` 的学期（按学期范围 ``[start, last_day]``）。

        范围含学期末边界，因此考试周（在课程结束之后）也归属该学期。
        """
        for semester in self.semesters:
            if semester.start <= d <= semester.last_day:
                return semester
        return None

    def current(self, when: date | None = None) -> Semester | None:
        """当前学期；``when`` 缺省为今天。无学期覆盖时返回 ``None``。"""
        return self.semester_for(when or date.today())

    def week_of(self, d: date) -> tuple[Semester, int] | None:
        """``d`` 所属的 ``(学期, 教学周)``；不在教学范围内返回 ``None``。"""
        semester = self.semester_for(d)
        if semester is None:
            return None
        week = semester.week_of(d)
        if week is None:
            return None
        return semester, week

    def next_event(self, when: date | None = None) -> CalendarEvent | None:
        """最近的未来事件；进行中的事件也算（其最后一天尚未过去）。

        以事件 ``start`` 升序取第一个满足 ``last_day >= when`` 的事件。
        """
        when = when or date.today()
        upcoming = [e for s in self.semesters for e in s.events if e.last_day >= when]
        if not upcoming:
            return None
        return min(upcoming, key=lambda e: (e.start, e.last_day))

    # -- 加载 -------------------------------------------------------------- #
    @classmethod
    def load(cls, refresh: bool = False) -> "AcademicCalendar":
        """抓取并解析校历主页；网络或解析失败时回退到内置常量。

        与 ``transit.schedule.TransitData.load`` 同口径：网络不可达与页面
        改版导致的解析失败都一律回退到 :data:`FALLBACK_DATA`，保证 ``load``
        在离线 / 页面结构变化时仍返回可用的校历。

        Args:
            refresh: 为 ``True`` 时先清掉本地 ETag 缓存再请求，强制拿最新内容。
        """
        if refresh:
            _drop_etag_cache()
        try:
            html, _etag = http_get_with_etag(CALENDAR_URL, cache_name=CACHE_NAME)
            return parse_calendar(html)
        except requests.RequestException as exc:
            logger.warning(
                "抓取校历失败（%s），改用内置离线数据（截至 2026 秋季）。",
                exc.__class__.__name__,
            )
            return cls.from_fallback()
        except ParseError as exc:
            logger.warning(
                "解析校历失败（%s：%s），页面结构可能已变化，"
                "改用内置离线数据（截至 2026 秋季）。",
                exc.__class__.__name__,
                exc,
            )
            return cls.from_fallback()

    @classmethod
    def from_fallback(cls) -> "AcademicCalendar":
        """用内置 ``FALLBACK_DATA`` 构建校历（离线兜底）。"""
        semesters = [
            _build_semester(name, events) for name, events in FALLBACK_DATA
        ]
        return cls(semesters=semesters)


#: 模块级 ``load``，等价于 :meth:`AcademicCalendar.load`。
load = AcademicCalendar.load


# --------------------------------------------------------------------------- #
# 文本预处理与 JS 提取
# --------------------------------------------------------------------------- #
def _repair_mojibake(text: str) -> str:
    """修复"UTF-8 被当成 ISO-8859-1 解码"造成的乱码。

    学校服务器返回 ``Content-Type: text/html``（无 charset），``requests``
    因此把 ``response.encoding`` 设为 ISO-8859-1，``response.text`` 会得到乱码；
    而 :func:`~westlake_survival._cache.http_get_with_etag` 返回的正是该
    ``response.text``。把乱码按 latin-1 还原成字节、再按 UTF-8 解码即可恢复。

    已经是正确文本时 ``encode("latin-1")`` 会抛 :class:`UnicodeEncodeError`
    （中文超出 latin-1 范围），此时原样返回——因此该函数是安全的幂等修复。
    """
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired


def _match_bracket(text: str, open_index: int) -> int:
    """返回与 ``text[open_index]`` 配对的收尾括号之后的下标。

    正确处理嵌套与字符串字面量（``'``、``"``、`` ` ``），忽略字符串内的括号。
    """
    open_ch = text[open_index]
    close_ch = {"[": "]", "{": "}", "(": ")"}[open_ch]
    depth = 0
    quote: str | None = None
    i = open_index
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ParseError(f"括号不配平：从下标 {open_index} 起未找到匹配的 {close_ch!r}")


def _extract_array(text: str, key: str) -> str:
    """提取 ``key: [ ... ]`` 中 ``[...]`` 的文本（含方括号）。"""
    key_match = re.search(rf"\b{re.escape(key)}\s*:", text)
    if not key_match:
        raise ParseError(f"页面中找不到键 {key!r}")
    open_index = text.find("[", key_match.end())
    if open_index == -1:
        raise ParseError(f"键 {key!r} 后找不到数组起始 '['")
    end_index = _match_bracket(text, open_index)
    return text[open_index:end_index]


def _extract_strings(array_text: str) -> list[str]:
    """从数组字面量文本中取出所有字符串字面量。"""
    return [
        m.group(2) if m.group(2) is not None else m.group(3)
        for m in re.finditer(r"(\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)')", array_text)
    ]


def _iter_top_level_arrays(array_text: str) -> list[str]:
    """把 ``[ [..], [..] ]`` 拆成内层各 ``[..]`` 的文本（含方括号）。"""
    inner: list[str] = []
    i = 1  # 跳过最外层 '['
    n = len(array_text) - 1  # 跳过最外层 ']'
    while i < n:
        ch = array_text[i]
        if ch == "[":
            end = _match_bracket(array_text, i)
            inner.append(array_text[i:end])
            i = end
            continue
        i += 1
    return inner


def _iter_objects(group_text: str) -> list[str]:
    """把 ``[ {..}, {..} ]`` 拆成各 ``{..}`` 的文本（含花括号）。"""
    objects: list[str] = []
    i = 1
    n = len(group_text) - 1
    while i < n:
        if group_text[i] == "{":
            end = _match_bracket(group_text, i)
            objects.append(group_text[i:end])
            i = end
            continue
        i += 1
    return objects


def _field(obj_text: str, key: str) -> str:
    """宽松地取出对象里 ``key`` 的值：支持单/双引号，缺省返回空串。"""
    match = re.search(
        rf"\b{re.escape(key)}\s*:\s*(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)')",
        obj_text,
    )
    if not match:
        return ""
    return match.group(1) if match.group(1) is not None else match.group(2)


def _parse_date(value: str) -> date | None:
    """把 ``2026-08-31`` / ``2026/08/31`` 解析成 :class:`datetime.date`。"""
    if not value:
        return None
    m = _DATE_RE.search(value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _build_semester(name: str, raw_events: list[dict]) -> Semester:
    """从原始事件字典列表构建 :class:`Semester`。

    学期起止取自标题含"课程开始"/"课程结束"的事件；匹配不到时抛
    :class:`ParseError`。
    """
    events: list[CalendarEvent] = []
    for raw in raw_events:
        title = (raw.get("title") or "").strip()
        start = _parse_date(raw.get("time") or "")
        if not title or start is None:
            logger.debug("跳过无法解析的校历条目：%r", raw)
            continue
        end = _parse_date(raw.get("endtime") or "")
        if end is not None and end <= start:
            end = None  # 结束日不晚于开始日，视为单日
        events.append(CalendarEvent(title=title, start=start, end=end, raw=dict(raw)))

    start = next((e.start for e in events if "课程开始" in e.title), None)
    end = next((e.start for e in events if "课程结束" in e.title), None)
    if start is None or end is None:
        raise ParseError(
            f"学期 {name!r} 缺少课程起止："
            f"课程开始={'未找到' if start is None else start}，"
            f"课程结束={'未找到' if end is None else end}"
        )
    if end < start:
        raise ParseError(f"学期 {name!r} 课程结束日 {end} 早于开始日 {start}")
    return Semester(name=name, start=start, end=end, events=events)


def parse_calendar(html: str) -> AcademicCalendar:
    """解析校历主页 HTML，返回 :class:`AcademicCalendar`。"""
    text = _repair_mojibake(html)
    seasons = _extract_strings(_extract_array(text, "seasonList"))
    content_array = _extract_array(text, "contentList")
    groups = _iter_top_level_arrays(content_array)

    if not seasons:
        raise ParseError("seasonList 为空，页面结构可能已变化")
    if not groups:
        raise ParseError("contentList 为空，页面结构可能已变化")
    if len(seasons) != len(groups):
        logger.warning(
            "seasonList(%d) 与 contentList(%d) 数量不一致，按较小者对齐。",
            len(seasons),
            len(groups),
        )

    semesters: list[Semester] = []
    for name, group_text in zip(seasons, groups):
        raw_events = [
            {
                "title": _field(obj, "title"),
                "time": _field(obj, "time"),
                "endtime": _field(obj, "endtime"),
            }
            for obj in _iter_objects(group_text)
        ]
        semesters.append(_build_semester(name, raw_events))
    return AcademicCalendar(semesters=semesters)


def _drop_etag_cache() -> None:
    """删除本地 ETag 缓存条目，令下一次请求变为无条件 GET。"""
    try:
        from westlake_survival import _cache

        path = _cache.cache_path(CACHE_NAME)
        if path.exists():
            path.unlink()
    except OSError:  # 缓存删不掉不应阻断加载
        logger.debug("删除 ETag 缓存失败", exc_info=True)


# --------------------------------------------------------------------------- #
# 离线兜底数据（实测于 2026-09-22；页面更新后应被在线解析覆盖）
# --------------------------------------------------------------------------- #
#: ``[(学期名, [事件, ...]), ...]``，结构与 :func:`parse_calendar` 的输出一致。
FALLBACK_DATA: list[tuple[str, list[dict]]] = [
    (
        "2026年春季",
        [
            {"title": "安排补考", "time": "2026-02-25", "endtime": "2026-03-01"},
            {"title": "春季学期研究生课程选课开始", "time": "2026-02-25", "endtime": ""},
            {"title": "本科生报到注册", "time": "2026-02-27", "endtime": ""},
            {"title": "春季学期课程开始", "time": "2026-03-02", "endtime": ""},
            {"title": "补考成绩提交截止", "time": "2026-03-06", "endtime": ""},
            {"title": "春季学期研究生课程选课结束", "time": "2026-03-13", "endtime": ""},
            {
                "title": "清明节放假（03月28日补上04月06日的课）",
                "time": "2026-04-04",
                "endtime": "2026-04-06",
            },
            {
                "title": "国际劳动节放假（05月09日补上05月01日的课，6月22-23日补上5月4-5日的课）",
                "time": "2026-05-01",
                "endtime": "2026-05-05",
            },
            {
                "title": "端午节放假（06月24日补上06月19日的课）",
                "time": "2026-06-19",
                "endtime": "2026-06-21",
            },
            {"title": "春季学期课程结束", "time": "2026-06-24", "endtime": ""},
            {"title": "期末考试周", "time": "2026-06-25", "endtime": "2026-07-03"},
            {"title": "课程缓考申请截止", "time": "2026-07-03", "endtime": ""},
            {"title": "本科生毕业典礼", "time": "2026-07-04", "endtime": ""},
            {"title": "研究生毕业典礼", "time": "2026-07-04", "endtime": ""},
            {"title": "本科生军训", "time": "2026-07-06", "endtime": "2026-07-19"},
            {"title": "课程成绩提交截止", "time": "2026-07-17", "endtime": ""},
        ],
    ),
    (
        "2026年秋季",
        [
            {"title": "本科生新生报到注册", "time": "2026-08-07", "endtime": ""},
            {"title": "本科生新生开学典礼", "time": "2026-08-08", "endtime": ""},
            {"title": "本科生新生暑期短学期", "time": "2026-08-09", "endtime": "2026-08-29"},
            {"title": "研究生新生报到注册", "time": "2026-08-21", "endtime": ""},
            {"title": "研究生开学典礼", "time": "2026-08-22", "endtime": ""},
            {"title": "研究生新生入学教育周", "time": "2026-08-24", "endtime": "2026-08-28"},
            {"title": "安排补考", "time": "2026-08-24", "endtime": "2026-08-28"},
            {"title": "秋季学期研究生课程选课", "time": "2026-08-26", "endtime": "2026-09-11"},
            {"title": "本科生报到注册", "time": "2026-08-27", "endtime": "2026-08-28"},
            {"title": "秋季学期课程开始", "time": "2026-08-31", "endtime": ""},
            {"title": "补考成绩提交截止", "time": "2026-09-04", "endtime": ""},
            {
                "title": "中秋节放假(9月20日补上9月25日的课）",
                "time": "2026-09-25",
                "endtime": "2026-09-27",
            },
            {
                "title": "国庆节放假(10月1-2日及5-7日的课顺延一周补齐）",
                "time": "2026-10-01",
                "endtime": "2026-10-07",
            },
            {"title": "学校运动会", "time": "2026-10-24", "endtime": ""},
            {"title": "秋季学期课程结束", "time": "2026-12-25", "endtime": ""},
            {"title": "元旦放假", "time": "2027-01-01", "endtime": ""},
            {"title": "期末考试周", "time": "2026-12-28", "endtime": "2027-01-08"},
            {"title": "课程缓考申请截止", "time": "2027-01-08", "endtime": ""},
            {"title": "课程成绩提交截止", "time": "2027-01-22", "endtime": ""},
        ],
    ),
]