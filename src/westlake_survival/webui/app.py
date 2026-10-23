"""Flask 应用工厂与路由。

本模块是 ``webui`` 的实现主体：一个 app factory + 一组只读路由。所有
依赖模块都通过 :func:`_import_module` **惰性导入**——``context`` / ``sis`` /
``ical`` 等尚未就绪或运行环境缺库时，页面优雅降级（卡片显示 ``—``、仍返回
200），而不是整页 500。

模板渲染的取数走模块级函数（:func:`_context_data` / :func:`_transit_data` /
:func:`_calendar_data` / :func:`_schedule_sessions`），测试通过 monkeypatch
这些「接缝」注入固定数据，无需真实网络。
"""

from __future__ import annotations

import importlib
import json
from datetime import date, datetime, time
from enum import Enum
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
)

#: 默认端口：2018 = 西湖大学建校年。
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 2018

#: 首页附加卡片字段（真实 ``Context.to_dict()`` 键 -> 中文标签）。
#: 日期 / 教学周另有「大字卡」，最近事件 / 下班车另有专表，故不在此列。
_CONTEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("weather", "天气"),
    ("aqi", "空气质量"),
    ("next_deadlines", "最近作业截止"),
)

_WEEKDAYS_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: 官网内容页的筛选枚举兜底值（对应模块未就绪时仍可渲染下拉框）。
#: 正常情况下优先读取 ``faculty.SCHOOL_NAMES`` / ``news.CATEGORIES``。
_FACULTY_SCHOOLS: tuple[str, ...] = ("理学院", "生命科学学院", "工学院", "医学院")
_NEWS_CATEGORIES: tuple[str, ...] = ("人物", "资讯", "学术", "校园", "招生", "媒体", "影像")


# --------------------------------------------------------------------------- #
# 惰性导入与数据接缝
# --------------------------------------------------------------------------- #
def _import_module(name: str):
    """导入 ``westlake_survival.<name>``；缺失/不可导入时返回 ``None``。

    这是 webui 对「模块尚未实现或可选依赖缺失」的兜底：整页仍可渲染。
    """
    try:
        return importlib.import_module(f"westlake_survival.{name}")
    except Exception:  # ImportError 及其它导入期错误
        return None


def _context_data(level: str = "normal") -> dict | None:
    """构造 context 快照 dict（``Context(level).to_dict()``）；模块缺失时 ``None``。

    这是首页与 ``/api/context`` 的唯一取数接缝（测试 monkeypatch 它）。
    真实 ``Context.to_dict()`` 不接受 level 参数——档位在构造时确定。
    """
    module = _import_module("context")
    if module is None:
        return None
    Context = getattr(module, "Context", None)
    Level = getattr(module, "Level", None)
    if Context is None:
        return None
    lvl: Any = level
    if Level is not None:
        lvl = getattr(Level, level.upper(), level)
    return Context(lvl).to_dict()


def _transit_data():
    """返回班车数据（``TransitData``）；模块缺失时 ``None``。"""
    module = _import_module("transit")
    if module is None:
        return None
    return module.transit()


def _calendar_data():
    """返回校历（``AcademicCalendar``）；模块缺失时 ``None``。"""
    module = _import_module("calendar")
    if module is None:
        return None
    return module.AcademicCalendar.load()


def _schedule_sessions():
    """返回当前课表 sessions（需登录）；模块缺失时返回 ``None``。

    调用方负责把 :class:`AuthError` / :class:`WestlakeError` 转成 503。
    """
    module = _import_module("sis")
    if module is None:
        return None
    return module.get_schedule()


def _shuttle_ical() -> str | None:
    """生成班车 ``.ics`` 文本；transit 模块缺失时 ``None``（测试接缝）。"""
    module = _import_module("transit")
    if module is None or not hasattr(module, "transit_to_ical"):
        return None
    return module.transit_to_ical()


def _events_data(days: int = 30, limit: int = 8):
    """返回未来 ``days`` 天内的活动预告（``EventItem`` 列表）；模块缺失时 ``None``。

    这是 ``/events`` 页活动区块的唯一取数接缝（测试 monkeypatch 它）。
    数据源是官网公开页面，失败时由调用方降级为隐藏区块。
    """
    module = _import_module("events")
    if module is None or not hasattr(module, "upcoming"):
        return None
    items = module.upcoming(days)
    return items[: max(0, limit)]


def _news_data(limit: int = 6):
    """返回最新「西湖新闻」（``NewsItem`` 列表）；模块缺失时 ``None``。

    这是 ``/events`` 页新闻区块的唯一取数接缝（测试 monkeypatch 它）。
    """
    module = _import_module("news")
    if module is None or not hasattr(module, "latest"):
        return None
    return module.latest(limit=limit)


def _schedule_ical(sessions) -> str | None:
    """把课表 sessions 转成 ``.ics`` 文本；ical 模块缺失时 ``None``（测试接缝）。"""
    module = _import_module("ical")
    if module is None or not hasattr(module, "courses_to_ical"):
        return None
    return module.courses_to_ical(sessions)


def _faculty_data(school: str | None = None, keyword: str | None = None):
    """返回教师名录（``FacultyMember`` 列表）；模块缺失时 ``None``。

    这是 ``/faculty`` 页的唯一取数接缝（测试 monkeypatch 它）。数据源是官网
    公开页面，失败时由调用方降级为提示文案。
    """
    module = _import_module("faculty")
    if module is None or not hasattr(module, "members"):
        return None
    return module.members(school=school or None, keyword=keyword or None)


def _news_list(limit: int = 30, category: str | None = None):
    """返回「西湖新闻」列表（``NewsItem`` 列表）；模块缺失时 ``None``。

    这是 ``/news`` 页的唯一取数接缝（测试 monkeypatch 它）。
    """
    module = _import_module("news")
    if module is None or not hasattr(module, "latest"):
        return None
    return module.latest(category=category or None, limit=limit)


def _search_data(keyword: str):
    """全站搜索 ``keyword``，返回 ``SearchResult``；模块缺失时 ``None``。

    这是 ``/search`` 页的唯一取数接缝（测试 monkeypatch 它）。
    """
    module = _import_module("search")
    if module is None or not hasattr(module, "search"):
        return None
    return module.search(keyword)


def _campus_dining():
    """返回餐饮点列表（``DiningSpot`` 列表）；模块缺失时 ``None``。"""
    module = _import_module("campus")
    if module is None or not hasattr(module, "dining"):
        return None
    return module.dining()


def _faculty_schools() -> tuple[str, ...]:
    """学院下拉选项：优先 ``faculty.SCHOOL_NAMES``，模块缺失时用兜底枚举。"""
    module = _import_module("faculty")
    names = getattr(module, "SCHOOL_NAMES", None) if module is not None else None
    return tuple(names) if names else _FACULTY_SCHOOLS


def _news_categories() -> tuple[str, ...]:
    """新闻分类下拉选项：优先 ``news.CATEGORIES``，模块缺失时用兜底枚举。"""
    module = _import_module("news")
    names = getattr(module, "CATEGORIES", None) if module is not None else None
    return tuple(names) if names else _NEWS_CATEGORIES


# --------------------------------------------------------------------------- #
# 模板过滤器
# --------------------------------------------------------------------------- #
def weekday_cn(value: Any) -> str:
    """把日期 / ISO 日期串 / 整数（0=周一）转成中文星期；无法识别返回原值。"""
    if value is None:
        return ""
    parsed = _coerce_date(value)
    if parsed is not None:
        return _WEEKDAYS_CN[parsed.weekday()]
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return _WEEKDAYS_CN[value % 7]
    text = str(value)
    for name in _WEEKDAYS_CN:
        if name in text:
            return name
    return text


def _coerce_date(value: Any) -> date | None:
    """尽量把 ``value`` 解释成 :class:`datetime.date`；失败返回 ``None``。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def fmt_date(value: Any) -> str:
    """格式化为 ``YYYY-MM-DD``；无法解析时返回原值的字符串形式。"""
    if value is None:
        return "—"
    parsed = _coerce_date(value)
    if parsed is None:
        return str(value)
    return parsed.strftime("%Y-%m-%d")


def days_until(value: Any, today: date | None = None) -> int | None:
    """返回 ``value`` 距今天的天数（未来为正）；无法解析返回 ``None``。"""
    parsed = _coerce_date(value)
    if parsed is None:
        return None
    base = today or date.today()
    return (parsed - base).days


# --------------------------------------------------------------------------- #
# JSON 安全化
# --------------------------------------------------------------------------- #
def _jsonable(obj: Any) -> Any:
    """把任意对象转成可 ``json.dumps`` 的结构（日期→ISO、枚举→值）。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (date, time)):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    return str(obj)


# --------------------------------------------------------------------------- #
# 视图辅助
# --------------------------------------------------------------------------- #
def _departure_key(table, time_str: str) -> tuple[str, str, str]:
    return (table.campus.name, table.day_kind.name, time_str)


def _shuttle_context() -> dict:
    """组装班车页上下文：数据、枚举顺序、高亮集合、错误信息。"""
    from westlake_survival.transit import Campus, DayKind

    data = None
    error = None
    try:
        data = _transit_data()
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        error = f"班车数据暂时不可用：{exc.__class__.__name__}"

    campuses = [c for c in Campus]
    day_kinds = [k for k in DayKind]

    # 键为 (校区英文名, 日别英文名)，模板按此取表。
    tables: dict[tuple[str, str], Any] = {}
    if data is not None:
        for campus in campuses:
            for kind in day_kinds:
                tables[(campus.name, kind.name)] = data.table(campus, kind)

    highlight: set[tuple[str, str, str]] = set()
    departures: list[tuple[Any, str]] = []
    if data is not None:
        try:
            departures = data.next_departures(limit=4)
            highlight = {_departure_key(tbl, ts) for tbl, ts in departures}
        except Exception:  # pragma: no cover - 降级：不高亮
            departures = []
            highlight = set()

    return {
        "error": error,
        "campuses": campuses,
        "day_kinds": day_kinds,
        "tables": tables,
        "highlight": highlight,
        "departures": departures,
    }


def _calendar_context() -> dict:
    """组装校历页上下文：当前学期、事件、周次进度。"""
    data = None
    error = None
    try:
        data = _calendar_data()
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        error = f"校历数据暂时不可用：{exc.__class__.__name__}"

    today = date.today()
    semester = None
    if data is not None:
        semester = data.current(today)

    progress = None
    if semester is not None:
        week = semester.week_of(today)
        total = semester.teaching_weeks()
        if week is not None and total:
            progress = {
                "week": week,
                "total": total,
                "percent": max(0, min(100, round(week / total * 100))),
            }

    events = list(semester.events) if semester is not None else []
    events.sort(key=lambda e: (e.start, e.last_day))

    return {
        "error": error,
        "semester": semester,
        "progress": progress,
        "events": events,
        "today": today,
    }


def _events_context() -> dict:
    """组装「讲座活动」页上下文：活动预告 + 西湖新闻。

    两个区块各自独立 try/except 降级：任一数据源失败只让对应区块隐藏
    （``None`` + 错误提示），页面绝不 500。
    """
    events = None
    events_error = None
    try:
        events = _events_data()
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        events_error = f"活动预告暂时不可用：{exc.__class__.__name__}"

    news = None
    news_error = None
    try:
        news = _news_data()
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        news_error = f"西湖新闻暂时不可用：{exc.__class__.__name__}"

    return {
        "events": events,
        "events_error": events_error,
        "news": news,
        "news_error": news_error,
        "today": date.today(),
    }


def _faculty_context(school: str = "", keyword: str = ""):
    """组装教师检索页上下文：选项、查询词、结果行、错误信息。

    取数接缝独立 try/except：数据源失败时 ``members`` 为 ``None`` 且给出
    中文提示，页面仍 200。``school`` / ``keyword`` 归一化为去空白后的字符串，
    空串表示「全部」。

    结果行用 :func:`getattr` 逐字段读取（而非直接解构 dataclass），这样
    ``faculty`` 模块后续给 ``FacultyMember`` / ``FacultyDetail`` 增删字段
    （如代表作）都不会让本页 500——缺字段时渲染为空。
    """
    school = (school or "").strip()
    keyword = (keyword or "").strip()

    members = None
    error = None
    searched = bool(school or keyword)
    if searched:
        # 至少给一个筛选条件才发起抓取：教师名录是全量列表（约 300 人），
        # 裸访问页面不应触发一次无谓的真请求。
        try:
            members = _faculty_data(school=school, keyword=keyword)
        except Exception as exc:  # pragma: no cover - 数据源异常时降级
            error = f"教师名录暂时不可用：{exc.__class__.__name__}"

    rows = [
        {
            "name": getattr(m, "name", "") or "",
            "name_en": getattr(m, "name_en", "") or "",
            "school": getattr(m, "school", "") or "",
            "subject": getattr(m, "subject", "") or "",
            "lab": getattr(m, "lab", "") or "",
            "url": getattr(m, "url", "") or "",
            # 另一个 agent 正在给 faculty 加「代表作」类字段：名字未定时逐个
            # 试探，任何一个都不存在也照常渲染（getattr 默认空串）。
            "works": (
                getattr(m, "works", "")
                or getattr(m, "representative_works", "")
                or getattr(m, "representative", "")
                or ""
            ),
        }
        for m in (members or [])
    ]

    return {
        "schools": _faculty_schools(),
        "school": school,
        "keyword": keyword,
        "rows": rows,
        "has_results": bool(rows),
        # 仅当至少一行带「代表作」时才渲染该列（避免整列空占位）。
        "has_works": any(row["works"] for row in rows),
        "error": error,
        "searched": searched,
    }


def _news_context(category: str = "", limit: int = 30):
    """组装西湖新闻页上下文：分类选项、当前分类、新闻列表、错误信息。"""
    category = (category or "").strip()

    news = None
    error = None
    try:
        news = _news_list(limit=limit, category=category)
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        error = f"西湖新闻暂时不可用：{exc.__class__.__name__}"

    return {
        "categories": _news_categories(),
        "category": category,
        "news": news,
        "error": error,
        "limit": limit,
    }


def _search_context(keyword: str = ""):
    """组装全站搜索页上下文：查询词、首页命中、错误信息。

    未给出关键词时不发起请求（``searched`` 为假）。命中列表从
    :class:`~westlake_survival.search.SearchResult` 归一化出来，模板不必关心
    结果对象的内部结构。
    """
    keyword = (keyword or "").strip()

    hits: list = []
    total = None
    error = None
    searched = bool(keyword)
    if searched:
        try:
            result = _search_data(keyword)
        except Exception as exc:  # pragma: no cover - 数据源异常时降级
            error = f"搜索暂时不可用：{exc.__class__.__name__}"
        else:
            raw_hits = getattr(result, "hits", None)
            if raw_hits is None and isinstance(result, (list, tuple)):
                # 兜底：接缝直接返回命中列表（无信封对象）时也照常渲染。
                raw_hits = result
            hits = [hit for hit in (raw_hits or [])]
            total = getattr(result, "total", None)
            if total is None:
                total = len(hits)

    return {
        "keyword": keyword,
        "hits": hits,
        "total": total,
        "error": error,
        "searched": searched,
    }


def _dining_context():
    """组装餐饮页上下文：按校区分组的餐饮点、错误信息。

    分组在渲染层之外完成（``groups`` 为 ``[(校区, [行, ...]), ...]``，行是
    普通 dict），保持模板简单；排序保持数据源原始顺序。字段用 :func:`getattr`
    读取，数据源对象缺字段时渲染为空而非报错。
    """
    spots = None
    error = None
    try:
        spots = _campus_dining()
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        error = f"餐饮数据暂时不可用：{exc.__class__.__name__}"

    order: list[str] = []
    buckets: dict[str, list[dict]] = {}
    for spot in spots or []:
        campus = getattr(spot, "campus", "") or "其它"
        if campus not in buckets:
            buckets[campus] = []
            order.append(campus)
        buckets[campus].append(
            {
                "name": getattr(spot, "name", "") or "",
                "address": getattr(spot, "address", "") or "",
                "food": getattr(spot, "food", "") or "",
                "hours": list(getattr(spot, "hours", None) or []),
            }
        )

    groups = [(campus, buckets[campus]) for campus in order]
    return {
        "groups": groups,
        "has_spots": bool(groups),
        "error": error,
    }


def _map_context(campus: str = ""):
    """组装地图页上下文：各校区地址/地图图片/全景/交通，失败降级为 ``error``。"""
    module = _import_module("campusmap")
    context: dict = {
        "error": None,
        "has_data": False,
        "campuses": [],
        "campus": campus,
    }
    if module is None or not hasattr(module, "campus_map"):
        context["error"] = "campusmap 模块不可用。"
        return context
    try:
        items = module.campus_map(campus or None)
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        context["error"] = f"校园地图数据暂时不可用：{exc.__class__.__name__}"
        return context
    context["campuses"] = [
        {
            "name": item.name,
            "address": item.address,
            "postcode": item.postcode,
            "map_url": item.map_url,
            "panoramas": [
                {"title": panorama.title, "url": panorama.url} for panorama in item.panoramas
            ],
            "traffic": item.traffic,
        }
        for item in items
    ]
    context["has_data"] = bool(context["campuses"])
    return context


def _program_data():
    """返回培养方案三页数据（overview / curriculum / majors 结果）；模块缺失时 ``None``。

    这是 ``/program`` 页的唯一取数接缝（测试可整体替换）。
    """
    module = _import_module("program")
    if module is None or not hasattr(module, "overview"):
        return None
    data = {
        "overview": module.overview(),
        "curriculum": module.curriculum(),
        "majors": module.majors(),
        "plans": None,
    }
    if hasattr(module, "major_plans"):
        try:
            data["plans"] = module.major_plans()
        except Exception:  # 培养方案页失败不应拖垮整页
            data["plans"] = None
    return data


def _courses_context(category: str = "", keyword: str = ""):
    """组装通识课程页上下文：按类别分组的课程表、提示与错误。

    与 :func:`_program_context` 同口径降级：取数失败只置 ``error``。
    """
    module = _import_module("program")
    context: dict = {
        "error": None,
        "has_courses": False,
        "groups": [],
        "notices": {},
        "count": 0,
        "category": category,
        "keyword": keyword,
        "source_url": "",
    }
    if module is None or not hasattr(module, "common_courses"):
        context["error"] = "program 模块不可用（缺少 common_courses）。"
        return context
    try:
        catalog = module.common_courses(
            category=category or None, keyword=keyword or None
        )
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        context["error"] = f"通识课程数据暂时不可用：{exc.__class__.__name__}"
        return context
    order: list[str] = []
    buckets: dict[str, list[dict]] = {}
    for course in catalog.courses:
        name = course.category or "其它"
        if name not in buckets:
            buckets[name] = []
            order.append(name)
        buckets[name].append(
            {
                "title": course.title,
                "subject": course.subject,
                "credits": course.credits,
                "semester": course.semester,
                "prerequisite": course.prerequisite,
                "teachers": [teacher.name for teacher in course.teachers],
            }
        )
    context["groups"] = [(name, buckets[name]) for name in order]
    context["has_courses"] = bool(order)
    context["notices"] = catalog.notices
    context["count"] = len(catalog.courses)
    context["source_url"] = catalog.url
    return context


def _program_context():
    """组装培养方案页上下文：培养目标、特色、课程体系栏目、专业列表。

    与 :func:`_dining_context` 同一降级口径：数据源异常时只置 ``error``，
    不让页面 500。字段全部转成普通 dict，保持模板简单。
    """
    data = None
    error = None
    try:
        data = _program_data()
    except Exception as exc:  # pragma: no cover - 数据源异常时降级
        error = f"培养方案数据暂时不可用：{exc.__class__.__name__}"

    context: dict = {
        "error": error,
        "has_data": False,
        "goal": "",
        "features": [],
        "summary": "",
        "majors": [],
        "plans": [],
        "sections": [],
        "source_url": "",
    }
    if not data:
        return context

    overview = data.get("overview")
    curriculum = data.get("curriculum")
    catalog = data.get("majors")
    if overview is not None:
        context["goal"] = getattr(overview.goal, "content_text", "")
        context["features"] = [
            {"title": f.title, "text": f.content_text} for f in getattr(overview, "features", [])
        ]
        context["source_url"] = getattr(overview, "url", "")
    if curriculum is not None:
        context["sections"] = [
            {
                "title": s.title,
                "text": s.content_text,
                "table": (
                    {
                        "name": s.table.name,
                        "rows": [{"name": r.name, "courses": r.items} for r in s.table.rows],
                    }
                    if s.table is not None
                    else None
                ),
            }
            for s in getattr(curriculum, "sections", [])
        ]
    if catalog is not None:
        context["summary"] = getattr(catalog, "summary", "")
        context["majors"] = [
            {"group": m.group, "name": m.name, "intro": m.intro_text}
            for m in getattr(catalog, "majors", [])
        ]
    plans = data.get("plans")
    if plans is not None:
        context["plans"] = [
            {
                "name": plan.name,
                "total_credits": plan.total_credits,
                "course_count": plan.course_count,
                "requirements": [
                    {
                        "title": req.title,
                        "credits": req.credits,
                        "note": req.note,
                        "courses": [
                            {
                                "name": course.name,
                                "credits": course.credits,
                                "group": course.group,
                                "prerequisite": course.prerequisite,
                            }
                            for course in req.courses
                        ],
                    }
                    for req in plan.requirements
                ],
                "warn_text": plan.warn_text,
            }
            for plan in getattr(plans, "majors", [])
        ]
    context["has_data"] = bool(context["goal"] or context["sections"] or context["majors"])
    return context


# --------------------------------------------------------------------------- #
# 应用工厂
# --------------------------------------------------------------------------- #
def create_app() -> Flask:
    """构建并返回 webui Flask 应用。"""
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    # 保证中文 JSON 直出、不被转义为 \uXXXX。
    app.json.ensure_ascii = False
    # 模板过滤器。
    app.jinja_env.filters["weekday_cn"] = weekday_cn
    app.jinja_env.filters["fmt_date"] = fmt_date
    app.jinja_env.filters["days_until"] = days_until

    # -- 首页：context 快照仪表盘 ---------------------------------------- #
    @app.route("/")
    def index():
        try:
            # 单次构造 VERBOSE 快照：一次 I/O 拿全所有档位字段（terse 的日期 /
            # 周次、normal 的最近事件 / 下班车、verbose 的天气 / AQI / 作业），
            # 避免重复构造与重复加载校历 / 班车。verbose 字段无数据时模板显示
            # 「—」。
            data = _context_data("verbose")
        except Exception as exc:
            # Context 内部已优雅降级，这里兜住任何意外，转成中文错误页。
            return (
                render_template(
                    "error.html",
                    code=500,
                    message="构造 context 快照时出错。",
                    detail=f"{exc.__class__.__name__}: {exc}",
                ),
                500,
            )

        ctx: dict = dict(data or {})
        # 已知字段补默认键，保证模板 `.get()` 有稳定结构。
        for key, _label in _CONTEXT_FIELDS:
            ctx.setdefault(key, None)

        # 最近事件 / 下班车直接用快照里的 dict 形式（不再单独加载校历 / 班车）。
        next_event = ctx.get("next_event")
        departures = ctx.get("next_shuttles") or []

        return render_template(
            "index.html",
            ctx=ctx,
            available=data is not None,
            fields=_CONTEXT_FIELDS,
            next_event=next_event,
            departures=departures,
            today=date.today(),
        )

    # -- 班车页 ----------------------------------------------------------- #
    @app.route("/shuttle")
    def shuttle():
        context = _shuttle_context()
        return render_template("shuttle.html", **context)

    # -- 校历页 ----------------------------------------------------------- #
    @app.route("/calendar")
    def calendar_page():
        context = _calendar_context()
        return render_template("calendar.html", **context)

    # -- 讲座活动页 ------------------------------------------------------- #
    @app.route("/events")
    def events_page():
        context = _events_context()
        return render_template("events.html", **context)

    # -- 教师检索页 ------------------------------------------------------- #
    @app.route("/faculty")
    def faculty_page():
        context = _faculty_context(
            school=request.args.get("school", ""),
            keyword=request.args.get("keyword", ""),
        )
        return render_template("faculty.html", **context)

    # -- 西湖新闻页 ------------------------------------------------------- #
    @app.route("/news")
    def news_page():
        context = _news_context(category=request.args.get("category", ""))
        return render_template("news.html", **context)

    # -- 全站搜索页 ------------------------------------------------------- #
    @app.route("/search")
    def search_page():
        context = _search_context(keyword=request.args.get("q", ""))
        return render_template("search.html", **context)

    # -- 餐饮页 ----------------------------------------------------------- #
    @app.route("/dining")
    def dining_page():
        context = _dining_context()
        return render_template("dining.html", **context)

    # -- 校园地图页 -------------------------------------------------------- #
    @app.route("/map")
    def map_page():
        context = _map_context(campus=request.args.get("campus", ""))
        return render_template("map.html", **context)

    # -- 通识课程页 -------------------------------------------------------- #
    @app.route("/courses")
    def courses_page():
        context = _courses_context(
            category=request.args.get("category", ""),
            keyword=request.args.get("q", ""),
        )
        return render_template("courses.html", **context)

    # -- 培养方案页 -------------------------------------------------------- #
    @app.route("/program")
    def program_page():
        context = _program_context()
        return render_template("program.html", **context)

    # -- iCalendar 下载 --------------------------------------------------- #
    @app.route("/ical/shuttle")
    def ical_shuttle():
        try:
            body = _shuttle_ical()
        except Exception as exc:
            return _hint_page(
                "班车数据不可用",
                f"生成班车日历时出错：{exc.__class__.__name__}: {exc}",
                status=503,
            )
        if body is None:
            return _hint_page(
                "班车数据不可用",
                "transit 模块未就绪，无法生成班车日历。",
                status=503,
            )
        return _ical_response(body, "westlake-shuttle.ics")

    @app.route("/ical/schedule")
    def ical_schedule():
        try:
            sessions = _schedule_sessions()
        except Exception as exc:
            # AuthError / WestlakeError / 其它：统一提示「需配置凭据」。
            return _hint_page(
                "需要配置凭据",
                "课表来自教务 SIS，需先配置登录凭据。"
                f"（{exc.__class__.__name__}: {exc}）",
                status=503,
            )
        if sessions is None:
            return _hint_page(
                "需要配置凭据",
                "课表来自教务 SIS，需先配置登录凭据（sis 模块未就绪）。",
                status=503,
            )

        try:
            body = _schedule_ical(sessions)
        except Exception as exc:
            return _hint_page(
                "课表导出失败",
                f"生成课表日历时出错：{exc.__class__.__name__}: {exc}",
                status=503,
            )
        if body is None:
            return _hint_page(
                "课表导出不可用",
                "ical 模块未就绪，无法生成课表日历。",
                status=503,
            )
        return _ical_response(body, "westlake-schedule.ics")

    # -- JSON API --------------------------------------------------------- #
    @app.route("/api/context")
    def api_context():
        try:
            data = _context_data("normal")
        except Exception as exc:
            return jsonify({"error": f"{exc.__class__.__name__}: {exc}"}), 500
        return Response(
            json.dumps(_jsonable(data), ensure_ascii=False, indent=2),
            mimetype="application/json",
        )

    @app.route("/api/shuttle")
    def api_shuttle():
        try:
            data = _transit_data()
        except Exception as exc:
            return jsonify({"error": f"{exc.__class__.__name__}: {exc}"}), 503
        if data is None:
            return jsonify({"error": "transit 数据不可用"}), 503
        payload = [
            {
                "campus": tbl.campus.value,
                "campus_name": tbl.campus.name,
                "day_kind": tbl.day_kind.value,
                "day_kind_name": tbl.day_kind.name,
                "direction_note": tbl.direction_note,
                "morning": list(tbl.morning),
                "noon": list(tbl.noon),
                "night": list(tbl.night),
            }
            for tbl in data.tables
        ]
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            mimetype="application/json",
        )

    # -- 错误页 ----------------------------------------------------------- #
    @app.errorhandler(404)
    def not_found(error):  # noqa: ARG001 - Flask 传入异常对象
        return (
            render_template(
                "error.html",
                code=404,
                message="页面不存在。",
                detail=f"没有找到路径 {request.path}。",
            ),
            404,
        )

    @app.errorhandler(500)
    def server_error(error):  # noqa: ARG001
        return (
            render_template(
                "error.html",
                code=500,
                message="服务器内部错误。",
                detail="请稍后重试；若持续失败，请查看服务端日志。",
            ),
            500,
        )

    return app


# --------------------------------------------------------------------------- #
# 响应辅助
# --------------------------------------------------------------------------- #
def _ical_response(body: str, filename: str) -> Response:
    """把 ics 文本包成带下载头的响应。"""
    return Response(
        body,
        mimetype="text/calendar",
        headers={
            "Content-Type": "text/calendar; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _hint_page(title: str, message: str, *, status: int = 503) -> tuple[str, int]:
    """返回一个纯文本提示页面（用于 ics 下载失败等场景）。"""
    html = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{title}</title></head>"
        "<body style=\"font-family:system-ui,sans-serif;max-width:40rem;"
        "margin:4rem auto;padding:0 1rem;color:#1f2933;line-height:1.6\">"
        f"<h1 style='font-size:1.4rem'>{title}</h1>"
        f"<p>{message}</p>"
        "<p><a href='/' style='color:#0b6e4f'>← 返回首页</a></p>"
        "</body></html>"
    )
    return html, status


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, debug: bool = False) -> None:
    """启动本地 web 服务并打印访问地址。"""
    app = create_app()
    url = f"http://{host}:{port}/"
    print(f"西湖生存手册 · 本地 Web 界面已启动：{url}")
    print(f"（仅绑定 {host}，局域网内其它机器无法访问；Ctrl+C 停止）")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":  # pragma: no cover
    run()
