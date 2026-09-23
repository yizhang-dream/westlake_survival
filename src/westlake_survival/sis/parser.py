"""SIS 课表解析：课程节次数据模型 + 两种来源的解析器。

本模块把 SIS（PeopleSoft Campus Solutions）的课表数据解析成统一的
:class:`ClassSession` 列表，供 :mod:`westlake_survival.ical` 生成日历。

两条来源路线：

1. **HTML 网格**（:func:`parse_schedule_html`）——登录后
   ``SSR_COMPONENT_FL.GBL``
   「View My Classes」页的 fluid 网格。结构随学期/页面版本变化，故写成防御式：
   优先按表头关键字定位列，找不到表头再按 PeopleSoft 导出表的默认列序兜底，
   最后再退回纯文本正则扫描。**列语义已由真实 ``ps.xls`` 证实**（见下方
   「实测校准」）；fluid 页的真实 DOM 元素 id 也已于 2026-09-23 登录链路
   实测确认（真实 ``<table>`` + ``<th>`` 表头、网格 id ``WL_STDNT_ENR_VW``，
   见下方「实测校准（2026-09-23）」）。
2. **ps.xls 导出**（:func:`parse_ps_xls`）——SIS「下载」按钮导出的文件
   **实为 HTML 表格伪装的 .xls**，且**行末缺 ``</tr>`` 标签**（实测于开源
   项目 wzsyyh/westlake-ics 的实战知识）。因此**不能**用严格 XML/``lxml``
   解析，必须用容错解析器：本模块自带基于 :class:`html.parser.HTMLParser`
   的 :class:`_TolerantTableParser`，在下一个 ``<tr>`` 开始时收尾上一行。

列结构（对照 wzsyyh/westlake-ics 的 ``ps2ics.py``）::

    班级 | 课程代码 | 课程名称 | 日期 | 时间 | 教室 | 教师 | 状态 | ...

其中「日期」列形如 ``2026/03/05 - 2026/06/18``，「时间」列形如
``星期四 13:30 到 15:55``；同一课程有多个 meeting pattern 时，单元格内以
``<br><br>``（解析后为双换行）分隔多值，日期/时间/教室按出现顺序一一对应。
教师列以 ``<br>``（单换行）或逗号分隔，同一教师重复出现需去重。

实测校准（2026-08-30 真实 ``ps.xls``，2026 秋学期，10 门课 / 13 条节次）
--------------------------------------------------------------------------
以下原先为「待校准」的假设，均已由真实样本证实（fixture 见
``src/test/sis/fixtures/ps_real_sanitized.xls``，教师名已脱敏）：

- **编码**：UTF-8（无 BOM），``<meta ... charset=utf-8>``；``_decode`` 的
  ``utf-8`` 首选分支即命中。
- **HTML 伪装**：首行 ``<!DOCTYPE html>`` + Oracle PeopleSoft 版权注释，
  正文为 ``<table border='1' ...>``。
- **缺 ``</tr>``**：确认——全文 11 个 ``<tr`` 仅 1 个 ``</tr>``，数据行末尾
  均无闭合标签；容错解析器（:class:`_TolerantTableParser`）正确分行。
- **表头**（真实表头 10 列，末两列为空 ``&nbsp;``）::

      班级 | 课程代码 | 课程名称 | 开始/结束日期 | 星期和时间 | 教室 | 任课教师 | 状态 | (空) | (空)

  关键字定位命中全部 8 个有值列（``开始/结束日期``→``date_range``、
  ``星期和时间``→``time_slot``、``任课教师``→``teacher``）；末两列空表头
  不参与映射。
- **「星期和时间」列格式**：**文字星期 + 真实时刻**（``星期四 13:30 到 15:05``），
  **不是节次编号**（如「第 3-4 节」）。故解析后直接得到钟点，无需节次换算。
- **多 meeting pattern**：单元格内以 ``<br />`` + CRLF 换行分隔（解析后为
  ``\n\r\n``），``_split_cell`` 的 ``\\n\\s*\\n`` 正确拆分；日期/时间/教室按序
  一一对应（真实样本中 ``PHY1004`` 2 个 pattern、``PHY1009`` 3 个 pattern）。
- **状态列**：真实值 ``已注册``（合成 fixture 用 ``已选``）。
- **教室格式**：``云谷校区E13-509``（校区名 + 楼栋-房间，无分隔空格）。
- **教师格式**：``中文名 (Pinyin NAME), 另一中文名 (Pinyin NAME)``，逗号分隔
  + 同一 pattern 重复出现（同一课程多 pattern 时教师单元格重复同一批姓名），
  去重后以 ``、`` 连接（真实样本中两位教师去重为 ``教师G、教师H``）。

实测校准（2026-09-23 真实登录链路，fluid「View My Classes」页）
--------------------------------------------------------------------------
登录链路三项待定全部落定（详见 :mod:`westlake_survival.sis.client`）：

- **真实课表页**：``SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL?Page=SSR_VW_CLASS_FL``
  （fluid 网格 ``WL_STDNT_ENR_VW``，原假设的 ``SSR_MD_SP_FL.GBL`` 对学生
  未授权）；**页面无学期选择控件**（``STRM`` 参数名假设不成立），默认展示
  当前学期。
- **导出**：网格头「Download to Excel」按钮 ``WL_STDNT_ENR_VW$hexcel$0``，
  ``POST ICAction`` 后响应页含 ``window.open('...ps.xls')`` 二段式下载。
- **fluid 网格 DOM**：真实 ``<table>`` + ``<th>`` 表头（本解析器的容错表格
  路线直接命中），单元格多值用 ``<br /> <br />`` 分隔（与 ps.xls 同源）。
- **英文 locale**：本项目登录走 ``languageCd=ENG``，网格表头/取值为英文
  （``Course Code`` / ``Mon 15:10 To 17:45`` / ``Enrolled``）。故
  :func:`parse_time_slot` 在中文（``星期四 13:30 到 15:05``）之外补齐英文
  缩写星期（``Mon``/``Thurs``...）与 ``To`` 分隔符；表头关键字补
  ``Course Title``。中文真实 ``ps.xls``（2026-08-30 样本）解析行为不变。

2026-09-23 实测：登录态页面解析与**当场导出**的 ``ps.xls`` 解析逐字段一致
（当日 10 门课 15 节次；与 8/30 样本 13 节次的差异源于选课变动，见
``src/test/sis/test_sis_client_real.py``）。

时区：所有时间均为中国标准时间 UTC+8（浮动本地时间，见 ical 模块）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping, Sequence

from westlake_survival.exceptions import ParseError

__all__ = [
    "ClassSession",
    "TableRow",
    "parse_schedule_html",
    "parse_ps_xls",
    "parse_date_range",
    "parse_time_slot",
    "parse_weeks",
    "WEEKDAY_NAMES",
    "DEFAULT_COLUMNS",
    "PERIOD_SCHEDULE",
    "slot_to_periods",
]

#: 「未知日期」哨兵；:meth:`ClassSession.from_row` 在缺日期字段时使用。
_EPOCH = date(1970, 1, 1)

#: 中文星期 → ISO weekday（1=周一 .. 7=周日）。
WEEKDAY_NAMES: dict[str, int] = {
    "星期一": 1,
    "周一": 1,
    "礼拜一": 1,
    "星期二": 2,
    "周二": 2,
    "礼拜二": 2,
    "星期三": 3,
    "周三": 3,
    "礼拜三": 3,
    "星期四": 4,
    "周四": 4,
    "礼拜四": 4,
    "星期五": 5,
    "周五": 5,
    "礼拜五": 5,
    "星期六": 6,
    "周六": 6,
    "礼拜六": 6,
    "星期日": 7,
    "星期天": 7,
    "周日": 7,
    "周天": 7,
    "礼拜日": 7,
    "礼拜天": 7,
    # 英文缩写/全称（2026-09-23 实测：ENG locale 网格/导出用 Mon/Thurs 等；
    # 查表时统一 lower()，中文键不受影响）。
    "mon": 1,
    "monday": 1,
    "tue": 2,
    "tues": 2,
    "tuesday": 2,
    "wed": 3,
    "weds": 3,
    "wednesday": 3,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "thursday": 4,
    "fri": 5,
    "friday": 5,
    "sat": 6,
    "saturday": 6,
    "sun": 7,
    "sunday": 7,
}

#: 反向映射（ISO weekday → 中文），ical 的 SUMMARY 等场景备用。
WEEKDAY_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}

#: 西湖大学官方排课「节次时间表」（13 节）。
#:
#: 每项 ``(start_hour, start_minute, end_hour, end_minute)``，索引 0 对应第 1 节。
#: 出处：开源项目 ``wzsyyh/westlake-ics`` 的 ``ps2wakeup.py``（``PERIOD_SCHEDULE``，
#: 按官方排课精确映射），及其 README 中「课表设置 → 节次时间」一节的 13 节对照表。
#: 该上游仓库未附 LICENSE 文件（截至 2026-09-22 未见授权声明），本表为**事实性
#: 排课时间数据**（不含可版权表达的代码），据此移植并在此注明来源。
#:
#: 说明：真实 ``ps.xls`` 的「星期和时间」列给的是**真实时刻**而非节次编号
#: （见模块 docstring），因此 :func:`parse_ps_xls` 不依赖本表；本表用于需要
#: 「节次 ↔ 时刻」换算的展示场景（如按节次排版的课表 UI），亦可用于校验
#: 解析出的时刻是否落在官方节次边界上（真实样本 13 条节次全部命中，见
#: ``src/test/sis/test_sis_parser_real.py``）。
PERIOD_SCHEDULE: tuple[tuple[int, int, int, int], ...] = (
    (8, 0, 8, 45),  # 第  1 节
    (8, 50, 9, 35),  # 第  2 节
    (9, 50, 10, 35),  # 第  3 节
    (10, 40, 11, 25),  # 第  4 节
    (11, 30, 12, 15),  # 第  5 节
    (13, 30, 14, 15),  # 第  6 节
    (14, 20, 15, 5),  # 第  7 节
    (15, 10, 15, 55),  # 第  8 节
    (16, 10, 16, 55),  # 第  9 节
    (17, 0, 17, 45),  # 第 10 节
    (18, 30, 19, 15),  # 第 11 节
    (19, 20, 20, 5),  # 第 12 节
    (20, 10, 20, 55),  # 第 13 节
)

#: 节次开始时刻（分钟数）→ 节次编号（1 起）。
_PERIOD_START_MINUTES = {
    h * 60 + m: index + 1
    for index, (h, m, _, _) in enumerate(PERIOD_SCHEDULE)
}

#: 节次结束时刻（分钟数）→ 节次编号（1 起）。
_PERIOD_END_MINUTES = {
    h * 60 + m: index + 1
    for index, (_, _, h, m) in enumerate(PERIOD_SCHEDULE)
}


def slot_to_periods(start: time, end: time) -> tuple[int, int] | None:
    """把起止时刻换算为 ``(起始节次, 结束节次)``（均 1 起）。

    仅当 **起始时刻恰为某节的上课时间** 且 **结束时刻恰为某节的下课时间**，
    且 ``end >= start`` 时返回；否则返回 ``None``（不猜测、不外推）。

    真实 ``ps.xls`` 的「星期和时间」列给的是真实时刻，本函数供需要按节次
    展示/排版的场景做换算，并可用于校验时刻是否落在官方节次边界上。
    """
    start_period = _PERIOD_START_MINUTES.get(start.hour * 60 + start.minute)
    end_period = _PERIOD_END_MINUTES.get(end.hour * 60 + end.minute)
    if start_period is None or end_period is None or end_period < start_period:
        return None
    return start_period, end_period


#: ps.xls / HTML 网格的默认列序（无表头时的兜底）。
DEFAULT_COLUMNS: tuple[str, ...] = (
    "class_section",
    "course_code",
    "title",
    "date_range",
    "time_slot",
    "room",
    "teacher",
    "status",
)

# --------------------------------------------------------------------------- #
# 正则
# --------------------------------------------------------------------------- #

#: 日期字面量 ``2026/03/05`` / ``2026-03-05``。
_DATE_RE = re.compile(r"(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})")

#: 日期范围分隔符：``-`` / ``–`` / ``—`` / ``~`` / ``到`` / ``至``。
_RANGE_SEP = r"\s*(?:-|–|—|~|～|到|至)\s*"

#: 日期范围：``2026/03/05 - 2026/06/18``（兼容 ``–``/``到`` 等分隔）。
_DATE_RANGE_RE = re.compile(
    r"(\d{4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,2})"
    + _RANGE_SEP
    + r"(\d{4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,2})"
)

#: 时间段：``星期四 13:30 到 15:55`` / 英文 locale ``Mon 15:10 To 17:45``
#: （星期可选、分隔符多种；``IGNORECASE`` 兼容 ``to``/``TO``，中文无大小写）。
_TIME_SLOT_RE = re.compile(
    r"(?P<weekday>(?:(?:星期|周|礼拜)[一二三四五六日天]"
    r"|mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?"
    r"|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)?)?\s*"
    r"(?P<start>\d{1,2}\s*:\s*\d{2})\s*"
    r"(?:到|至|\bto\b|-|–|—|~|～)\s*"
    r"(?P<end>\d{1,2}\s*:\s*\d{2})",
    re.IGNORECASE,
)

#: 周次：``1-16周`` / ``1,3,5`` / ``1-8,10-16周`` / ``第1-16周``。
_WEEKS_RE = re.compile(r"([\d\s,，、\-–—~]+)\s*周")

#: 表头关键字 → 规范化列名。按「包含」匹配，大小写不敏感。
_HEADER_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("课程代码", "course_code"),
    ("课程号", "course_code"),
    ("course code", "course_code"),
    ("课程名称", "title"),
    ("课程名", "title"),
    ("course name", "title"),
    ("course title", "title"),  # 2026-09-23 实测：ENG locale 网格表头
    ("课程标题", "title"),
    ("日期", "date_range"),
    ("date", "date_range"),
    ("时间", "time_slot"),
    ("time", "time_slot"),
    ("教室", "room"),
    ("room", "room"),
    ("地点", "room"),
    ("教师", "teacher"),
    ("老师", "teacher"),
    ("instructor", "teacher"),
    ("teacher", "teacher"),
    ("周次", "weeks"),
    ("weeks", "weeks"),
    ("状态", "status"),
    ("status", "status"),
    ("班级", "class_section"),
    ("class", "class_section"),
)

#: 表头行判定：命中任一关键字即认为该行是表头。
_HEADER_HINTS = ("课程代码", "课程名称", "日期", "时间", "教室", "教师", "course code")


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class ClassSession:
    """一次「上课节次」：同一门课在某个星期几、某个时间段、某段日期范围内。

    同一门课若一周上两次，就是两个 :class:`ClassSession`（weekday 不同）。
    ``raw`` 保留解析来源的原始文本，便于排查。

    Attributes:
        title: 课程名称。
        course_code: 课程代码（如 ``CS101``）。
        teacher: 任课教师（多个以 ``、`` 连接）。
        room: 教室。
        weekday: ISO 星期，``1``=周一 .. ``7``=周日。
        start_time: 上课时间。
        end_time: 下课时间。
        date_start: 该节次生效起始日。
        date_end: 该节次生效结束日（单次课等于 ``date_start``）。
        weeks: 明确的上课周次（1 起）；``None`` 表示「区间内每周都上」。
        raw: 原始字段文本。
    """

    title: str = ""
    course_code: str = ""
    teacher: str = ""
    room: str = ""
    weekday: int = 1
    start_time: time = time(0, 0)
    end_time: time = time(0, 0)
    date_start: date = _EPOCH
    date_end: date = _EPOCH
    weeks: tuple[int, ...] | None = None
    raw: dict = field(default_factory=dict)

    # -------------------------------------------------------------- 构造

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ClassSession":
        """从一行「字段 → 原始文本」的映射构造节次，**容忍缺字段**。

        接受规范化列名（``course_code`` / ``title`` / ``date_range`` /
        ``time_slot`` / ``room`` / ``teacher`` / ``weeks``）以及若干中文别名
        （``课程代码`` / ``课程名称`` / ``日期`` / ``时间`` / ``教室`` /
        ``教师`` / ``周次``）。缺列或缺值时字段留空、日期退回 :data:`_EPOCH`、
        星期退回周一、时间退回 ``00:00``，**绝不抛异常**。

        日期/时间既可直接给 ``date_start``/``date_end``/``weekday``/
        ``start_time``/``end_time``，也可给字符串 ``date_range``/``time_slot``
        由本方法解析。
        """
        data = dict(row or {})

        title = _text(_pick(data, "title", "课程名称", "课程名", "course_name"))
        course_code = _text(
            _pick(data, "course_code", "课程代码", "课程号", "code")
        )
        teacher = _clean_teacher(_text(_pick(data, "teacher", "教师", "老师")))
        room = _text(_pick(data, "room", "教室", "地点"))

        # 日期
        date_start = _as_date(_pick(data, "date_start"))
        date_end = _as_date(_pick(data, "date_end"))
        if date_start is None or date_end is None:
            raw_range = _text(_pick(data, "date_range", "日期", "date"))
            parsed = parse_date_range(raw_range) if raw_range else None
            if parsed is not None:
                date_start = date_start or parsed[0]
                date_end = date_end or parsed[1]
            elif raw_range:
                single = _parse_single_date(raw_range)
                if single is not None:
                    date_start = date_start or single
                    date_end = date_end or single
        date_start = date_start or _EPOCH
        date_end = date_end or date_start

        # 星期与时间
        weekday = _as_weekday(_pick(data, "weekday"))
        start_time = _as_time(_pick(data, "start_time"))
        end_time = _as_time(_pick(data, "end_time"))
        if weekday is None or start_time is None or end_time is None:
            raw_slot = _text(_pick(data, "time_slot", "时间", "time"))
            parsed_slot = parse_time_slot(raw_slot) if raw_slot else None
            if parsed_slot is not None:
                weekday = weekday if weekday is not None else parsed_slot[0]
                start_time = start_time or parsed_slot[1]
                end_time = end_time or parsed_slot[2]

        weeks = _as_weeks(_pick(data, "weeks", "周次"))

        return cls(
            title=title,
            course_code=course_code,
            teacher=teacher,
            room=room,
            weekday=weekday or 1,
            start_time=start_time or time(0, 0),
            end_time=end_time or time(0, 0),
            date_start=date_start,
            date_end=date_end,
            weeks=weeks,
            raw={str(k): _text(v) for k, v in data.items()},
        )

    # -------------------------------------------------------------- 序列化

    @property
    def periods(self) -> tuple[int, int] | None:
        """起止时刻对应的 ``(起始节次, 结束节次)``（见 :func:`slot_to_periods`）。

        真实 ``ps.xls`` 的「星期和时间」列给的是真实时刻；本属性按官方
        节次时间表（:data:`PERIOD_SCHEDULE`）换算节次，供按节次展示的场景
        使用。时刻不落在官方节次边界上时返回 ``None``。
        """
        return slot_to_periods(self.start_time, self.end_time)

    def to_dict(self) -> dict:
        """转成可 JSON 序列化的字典（缓存用）。"""
        return {
            "title": self.title,
            "course_code": self.course_code,
            "teacher": self.teacher,
            "room": self.room,
            "weekday": self.weekday,
            "start_time": self.start_time.strftime("%H:%M"),
            "end_time": self.end_time.strftime("%H:%M"),
            "date_start": self.date_start.isoformat(),
            "date_end": self.date_end.isoformat(),
            "weeks": list(self.weeks) if self.weeks is not None else None,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClassSession":
        """从 :meth:`to_dict` 的产物恢复（缓存用，容忍缺字段）。"""
        weeks = data.get("weeks")
        return cls(
            title=_text(data.get("title")),
            course_code=_text(data.get("course_code")),
            teacher=_text(data.get("teacher")),
            room=_text(data.get("room")),
            weekday=int(data.get("weekday") or 1),
            start_time=_parse_clock(data.get("start_time")) or time(0, 0),
            end_time=_parse_clock(data.get("end_time")) or time(0, 0),
            date_start=_parse_iso_date(data.get("date_start")) or _EPOCH,
            date_end=_parse_iso_date(data.get("date_end")) or _EPOCH,
            weeks=tuple(int(w) for w in weeks) if weeks is not None else None,
            raw=dict(data.get("raw") or {}),
        )


#: 类型别名：解析器产出的「一行单元格文本」。
TableRow = list[str]


# --------------------------------------------------------------------------- #
# 容错 HTML 表格解析（ps.xls 的关键）
# --------------------------------------------------------------------------- #
class _TolerantTableParser(HTMLParser):
    """容错表格解析器：**行末缺 ``</tr>`` 也能正确分行**。

    与 wzsyyh/westlake-ics 的 ``TableParser`` 同源策略：

    - 遇到新的 ``<tr>`` 时，若上一行已积累单元格则先收尾入列（弥补缺
      ``</tr>``）；
    - ``<br>`` 记为换行（同一单元格内多值分隔）；
    - ``</table>`` / ``</body>`` / ``</html>`` 与 ``close()`` 兜底收尾最后一行；
    - ``<th>`` 单元格（表头）单独记录到 :attr:`header`，不混入数据行。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[TableRow] = []
        self.header: TableRow | None = None
        self._row: TableRow | None = None
        self._cell: list[str] | None = None
        self._in_header = False

    # -- 内部 ---------------------------------------------------------

    def _flush_row(self) -> None:
        if self._row:
            if self._in_header and self.header is None:
                self.header = self._row
            else:
                self.rows.append(self._row)
        self._row = None
        self._in_header = False

    def _flush_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
        self._cell = None

    # -- HTMLParser 钩子 ----------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            # 缺 </tr> 容错：新行开始时先收尾上一行。
            self._flush_cell()
            self._flush_row()
            self._row = []
            self._in_header = False
        elif tag in ("td", "th"):
            self._flush_cell()
            if self._row is None:
                self._row = []
            self._cell = []
            if tag == "th":
                # 行级判定：本行出现过 <th> 即视为表头行（与末尾单元格无关）。
                self._in_header = True
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 自闭合 <br/> 等。
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_cell()
            self._flush_row()
        elif tag in ("table", "body", "html"):
            self._flush_cell()
            self._flush_row()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def close(self) -> None:
        super().close()
        self._flush_cell()
        self._flush_row()


def _parse_tables(html: str) -> tuple[TableRow | None, list[TableRow]]:
    """用容错解析器抽取 (表头行, 数据行列表)。

    表头行有两种来源：``<th>`` 行（:attr:`_TolerantTableParser.header`），
    或数据行里首个「看起来像表头」的行（PeopleSoft fluid 网格常用 ``<td>``
    承载列头）。后者会从数据行中剔除。
    """
    parser = _TolerantTableParser()
    parser.feed(html or "")
    parser.close()
    rows = [[cell.strip() for cell in row] for row in parser.rows]
    header = [cell.strip() for cell in parser.header] if parser.header else None

    if header is None:
        for index, row in enumerate(rows):
            if _looks_like_header(row):
                header = row
                del rows[index]
                break
    return header, rows


# --------------------------------------------------------------------------- #
# 单元格拆分 / 归一化
# --------------------------------------------------------------------------- #
def _split_cell(text: str) -> list[str]:
    """把单元格内的多值（``<br><br>`` → 双换行）拆成列表。"""
    if not text:
        return []
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _clean_teacher(text: str) -> str:
    """教师单元格去重：按换行/逗号拆分后去重，以 ``、`` 连接。"""
    if not text:
        return ""
    names = re.split(r"[,，\n、;；]+", text)
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        name = name.strip().strip(",，、;；")
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return "、".join(result)


def _text(value: Any) -> str:
    """把任意值转成去首尾空白的字符串（``None`` → ``""``）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    """按顺序取第一个存在且非空的键值。"""
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


# --------------------------------------------------------------------------- #
# 字段解析
# --------------------------------------------------------------------------- #
def _parse_date_literal(text: str) -> date | None:
    match = _DATE_RE.search(text or "")
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_single_date(text: str) -> date | None:
    return _parse_date_literal(text)


def parse_date_range(text: str) -> tuple[date, date] | None:
    """解析日期范围 ``2026/03/05 - 2026/06/18``（兼容 ``–``/``—``/``到``/``至``）。

    只有单个日期时返回 ``(d, d)``；完全无法解析返回 ``None``。
    """
    if not text:
        return None
    match = _DATE_RANGE_RE.search(text)
    if match:
        start = _parse_date_literal(match.group(1))
        end = _parse_date_literal(match.group(2))
        if start and end:
            return (start, end) if start <= end else (end, start)
    single = _parse_date_literal(text)
    if single:
        return (single, single)
    return None


def _parse_clock(text: Any) -> time | None:
    if isinstance(text, time):
        return text
    value = _text(text)
    match = re.search(r"(\d{1,2})\s*:\s*(\d{2})", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def parse_time_slot(text: str) -> tuple[int, time, time] | None:
    """解析时间段 ``星期四 13:30 到 15:55`` → ``(weekday, start, end)``。

    星期可省略（返回 ``weekday=1``）；完全无法解析返回 ``None``。
    """
    if not text:
        return None
    match = _TIME_SLOT_RE.search(text)
    if not match:
        return None
    weekday = WEEKDAY_NAMES.get((match.group("weekday") or "").strip().lower(), 1)
    start = _parse_clock(match.group("start"))
    end = _parse_clock(match.group("end"))
    if start is None or end is None:
        return None
    return weekday, start, end


def parse_weeks(text: str) -> tuple[int, ...] | None:
    """解析周次 ``1-16周`` / ``1,3,5`` / ``1-8,10-16周`` → 升序元组。

    解析不出返回 ``None``（表示「区间内每周都上」）。
    """
    if not text:
        return None
    match = _WEEKS_RE.search(text)
    body = match.group(1) if match else text
    if not re.search(r"\d", body):
        return None
    weeks: set[int] = set()
    for chunk in re.split(r"[,，、;；]+", body):
        chunk = chunk.strip()
        if not chunk:
            continue
        rng = re.match(r"^(\d+)\s*(?:-|–|—|~|～|至)\s*(\d+)$", chunk)
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if lo > hi:
                lo, hi = hi, lo
            weeks.update(range(lo, hi + 1))
            continue
        for number in re.findall(r"\d+", chunk):
            weeks.add(int(number))
    if not weeks:
        return None
    return tuple(sorted(weeks))


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _parse_date_literal(value)
    return None


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return _parse_date_literal(text)


def _as_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    return _parse_clock(value)


def _as_weekday(value: Any) -> int | None:
    if isinstance(value, int) and 1 <= value <= 7:
        return value
    text = _text(value)
    if text in WEEKDAY_NAMES:
        return WEEKDAY_NAMES[text]
    if text.lower() in WEEKDAY_NAMES:
        return WEEKDAY_NAMES[text.lower()]
    if text.isdigit() and 1 <= int(text) <= 7:
        return int(text)
    return None


def _as_weeks(value: Any) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list, set)):
        try:
            return tuple(sorted({int(v) for v in value}))
        except (TypeError, ValueError):
            return None
    return parse_weeks(_text(value))


# --------------------------------------------------------------------------- #
# 列定位与行展开
# --------------------------------------------------------------------------- #
def _looks_like_header(cells: Sequence[str]) -> bool:
    """该行是否像表头行。

    判定：整行不含「日期范围 + 时间段」这类数据特征（``2026/03/05``、
    ``13:30 到 15:55``），且至少命中两个表头关键字（如「课程代码」「时间」
    「教室」）。要求命中两个可避免把课程名里含「时间」二字的正常行误判成表头。
    """
    joined = " ".join(cells)
    # 含日期范围或时间段的一律视为数据行。
    if _DATE_RANGE_RE.search(joined) or _TIME_SLOT_RE.search(joined):
        return False
    low = joined.lower()
    hits = sum(1 for hint in _HEADER_HINTS if hint.lower() in low)
    return hits >= 2


def _map_columns(header: Sequence[str]) -> dict[int, str]:
    """把表头单元格映射为 ``{列索引: 规范化列名}``（同名列取先出现者）。"""
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for index, cell in enumerate(header):
        low = cell.strip().lower()
        if not low:
            continue
        for keyword, name in _HEADER_KEYWORDS:
            if keyword in low:
                if name not in used:
                    mapping[index] = name
                    used.add(name)
                break
    return mapping


def _row_to_fields(
    cells: Sequence[str], columns: Mapping[int, str]
) -> dict[str, str]:
    """按列映射把一行单元格变成 ``{字段: 文本}``（多值单元格保持原样）。"""
    fields: dict[str, str] = {}
    if columns:
        for index, name in columns.items():
            if index < len(cells):
                fields[name] = cells[index]
    else:
        # 无表头：按 PeopleSoft 导出表默认列序兜底。
        for index, name in enumerate(DEFAULT_COLUMNS):
            if index < len(cells):
                fields[name] = cells[index]
    return fields


def _expand_fields(fields: Mapping[str, str]) -> list[ClassSession]:
    """把一行「字段 → 文本」展开成若干 :class:`ClassSession`。

    日期 / 时间 / 教室三列都是多值单元格，按出现顺序一一配对；日期与时间长度
    不一致时取最短（与 wzsyyh/westlake-ics 一致）。若缺少日期或时间，退化为单条。

    教室语义：教室按出现顺序与各 meeting pattern 一一配对；当**教室数少于
    pattern 数**（如一行两个 meeting pattern 却只填了一个教室）时，多出的行
    不再回落到第一个教室（那会造成"张冠李戴"），而是把 ``room`` 置空串——
    即空串表示"该 pattern 未提供教室"，与 :meth:`ClassSession.from_row` 缺列时
    的默认值一致。教室数多于 pattern 数时多余教室被忽略。
    """
    dates = _split_cell(fields.get("date_range", ""))
    times = _split_cell(fields.get("time_slot", ""))
    rooms = _split_cell(fields.get("room", ""))
    weeks_text = fields.get("weeks", "")

    title = _text(fields.get("title", ""))
    course_code = _text(fields.get("course_code", ""))
    teacher = _clean_teacher(fields.get("teacher", ""))

    # 完全没有课程信息则视为空行。
    if not (title or course_code):
        return []

    if not dates and not times:
        # 没有任何时间信息：产出单条（日期/时间退化为哨兵），保留课程本体。
        return [
            ClassSession(
                title=title,
                course_code=course_code,
                teacher=teacher,
                room=rooms[0] if rooms else "",
                raw=dict(fields),
            )
        ]

    count = min(len(dates), len(times)) if (dates and times) else max(
        len(dates), len(times)
    )
    sessions: list[ClassSession] = []
    for index in range(count):
        date_text = dates[index] if index < len(dates) else ""
        time_text = times[index] if index < len(times) else ""
        # 教室按序一一配对；教室数少于 pattern 数时缺教室的行置空串，
        # 不回落到 rooms[0]（否则会把第一个教室错配到后续 pattern 上）。
        room = rooms[index] if index < len(rooms) else ""
        parsed = ClassSession.from_row(
            {
                "title": title,
                "course_code": course_code,
                "teacher": teacher,
                "room": room,
                "date_range": date_text,
                "time_slot": time_text,
                "weeks": weeks_text,
            }
        )
        parsed.raw = dict(fields)
        sessions.append(parsed)
    return sessions


def _sessions_from_rows(header: TableRow | None, rows: Iterable[TableRow]) -> list[ClassSession]:
    columns = _map_columns(header) if header else {}
    sessions: list[ClassSession] = []
    for cells in rows:
        if not any(cell.strip() for cell in cells):
            continue
        if _looks_like_header(cells):
            # 数据区里混入的重复表头（多表格拼接时常见）跳过。
            continue
        fields = _row_to_fields(cells, columns)
        sessions.extend(_expand_fields(fields))
    return sessions


# --------------------------------------------------------------------------- #
# 纯文本兜底解析（HTML 网格结构未知时）
# --------------------------------------------------------------------------- #
def _strip_tags(html: str) -> str:
    """粗暴去标签，得到近似可见文本（保留换行）。"""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return text


def _parse_from_text(text: str) -> list[ClassSession]:
    """纯文本兜底：按「日期范围 + 时间段」的出现顺序配对。

    课程名/教室/教师无法可靠定位，留空并标注在 ``raw`` 中。

    实测校准确认（2026-09-23）：真实课表页是 ``<table>`` + ``<th>`` 表头的
    fluid 网格（``WL_STDNT_ENR_VW``），主表格路线即可精确解析，本兜底仅在
    「结构未知时不至于完全解析不出」。
    """
    flat = _strip_tags(text)
    date_ranges = [m.group(0) for m in _DATE_RANGE_RE.finditer(flat)]
    slots = [m.group(0) for m in _TIME_SLOT_RE.finditer(flat)]
    if not date_ranges or not slots:
        return []
    count = min(len(date_ranges), len(slots))
    sessions: list[ClassSession] = []
    for index in range(count):
        sessions.append(
            ClassSession.from_row(
                {"date_range": date_ranges[index], "time_slot": slots[index]}
            )
        )
    return sessions


# --------------------------------------------------------------------------- #
# 公开解析入口
# --------------------------------------------------------------------------- #
def parse_schedule_html(html: str) -> list[ClassSession]:
    """解析 SIS 课表 HTML（fluid「我的日程」网格），返回节次列表。

    策略（防御式，逐级降级）：

    1. 用容错表格解析器找表头行（含「日期/时间/课程名称」等关键字），按列名
       定位后展开数据行；
    2. 找不到可用表格时，退回纯文本正则扫描（:func:`_parse_from_text`）。

    解析不到任何课程时抛 :class:`~westlake_survival.exceptions.ParseError`
    （便于区分「页面结构变了」与「这学期没课」——调用方可用
    :func:`parse_ps_xls` 或看 :attr:`ClassSession.raw` 排查）。
    """
    if not html or not html.strip():
        raise ParseError("课表 HTML 为空，无法解析。")

    header, rows = _parse_tables(html)
    sessions = _sessions_from_rows(header, rows)
    if sessions:
        return sessions

    sessions = _parse_from_text(html)
    if sessions:
        return sessions

    raise ParseError(
        "未能从课表 HTML 中解析出任何课程节次；"
        "页面结构可能与预期不符，请反馈课表页 HTML 以便校准。"
    )


def parse_ps_xls(content: bytes | str) -> list[ClassSession]:
    """解析 SIS 导出的 ``ps.xls``（HTML 表格伪装的 .xls），返回节次列表。

    关键点：文件**行末缺 ``</tr>``**，必须用容错解析器（见
    :class:`_TolerantTableParser`），不能用严格 XML。

    已由 2026-08-30 真实 ``ps.xls`` 证实：编码为 **UTF-8**（无 BOM），
    正文为 ``<!DOCTYPE html>`` + PeopleSoft ``<table>``，11 个 ``<tr`` 仅 1 个
    ``</tr>``（数据行均无闭合标签）；表头 8 个有值列 + 2 个空列，关键字定位
    全部命中；「星期和时间」列为**文字星期 + 真实时刻**（非节次编号）。详见
    模块 docstring 的「实测校准」一节。

    Args:
        content: 文件字节或文本。字节时按 ``utf-8`` 解码（真实样本即 UTF-8），
            失败退回 ``gbk`` / ``gb18030``。

    Returns:
        课程节次列表；同一课程多个 meeting pattern 会展开为多条。

    Raises:
        ParseError: 内容不是 HTML 表格（``<table`` 都不含）时。
    """
    if isinstance(content, bytes):
        text = _decode(content)
    else:
        text = content or ""

    if "<table" not in text.lower() and "<tr" not in text.lower():
        raise ParseError(
            "ps.xls 内容不含 HTML 表格；请确认是从 SIS「我的课表 → 下载」"
            "导出的文件（实为 HTML 表格伪装的 .xls）。"
        )

    header, rows = _parse_tables(text)
    sessions = _sessions_from_rows(header, rows)
    if not sessions:
        sessions = _parse_from_text(text)
    if not sessions:
        raise ParseError("ps.xls 中未解析出任何课程，文件结构可能与预期不符。")
    return sessions


def _decode(content: bytes) -> str:
    """解码导出文件：优先 UTF-8，失败退回 GBK，最后容错忽略。

    真实 ``ps.xls``（2026-08-30）实测为 **UTF-8 无 BOM**（``<meta
    charset=utf-8>``），首选分支即命中；GBK 分支保留给历史/异常导出。
    """
    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")