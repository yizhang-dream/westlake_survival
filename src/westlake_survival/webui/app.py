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
import logging
import os
import time as _time_mod

from westlake_survival.discovery import SERVICE_REGISTRY
import re as _re
from datetime import date, datetime, time
from enum import Enum
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
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
logger = logging.getLogger(__name__)

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


def _pretty(data: Any, limit: int = 900) -> str:
    """把数据转成带缩进的 JSON 文本，超长截断（页面只展示样例）。"""
    try:
        text = json.dumps(_jsonable(data), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return "（该接口无法序列化为 JSON 样例）"
    if len(text) > limit:
        return text[:limit] + chr(10) + "…（已截断）"
    return text


def _api_doc_context():
    """组装 API 说明页上下文：每个接口的路径、用途、真实样例。

    样例来自与接口本身相同的取数函数；任一数据源失败只影响该条样例，
    不让整页 500。
    """
    endpoints: list[dict] = []

    def add(path: str, title: str, note: str, kind: str, producer) -> None:
        row = {"path": path, "title": title, "note": note, "kind": kind, "sample": "", "error": ""}
        try:
            data = producer()
            row["sample"] = data if isinstance(data, str) else _pretty(data)
        except Exception as exc:  # pragma: no cover - 数据源异常只影响样例
            row["error"] = f"{exc.__class__.__name__}: {exc}"
        endpoints.append(row)

    add(
        "/api/context",
        "当前快照",
        "日期、周次、学期、最近事件、下班车、天气与空气质量。",
        "json",
        lambda: _context_data("normal"),
    )
    add(
        "/api/capabilities",
        "能力清单",
        "CLI / MCP / WebUI 全部入口及其凭据需求。",
        "json",
        lambda: _import_module("capabilities").as_dict(),
    )
    add(
        "/api/shuttle",
        "班车时刻表",
        "三校区 × 工作日/周末/节假日的班车时刻分档。",
        "json",
        lambda: [
            {
                "campus": tbl.campus.value,
                "campus_name": tbl.campus.name,
                "day_kind": tbl.day_kind.value,
                "day_kind_name": tbl.day_kind.name,
                "morning": list(tbl.morning)[:3],
                "noon": list(tbl.noon)[:3],
                "night": list(tbl.night)[:3],
            }
            for tbl in (_transit_data().tables if _transit_data() is not None else [])
        ],
    )
    add(
        "/ical/shuttle",
        "班车日历（ICS）",
        "订阅到日历应用；只在请求时生成，不入缓存文件。",
        "ics",
        lambda: "（ICS 文本，浏览器直接下载；此处不展示样例）",
    )
    add(
        "/ical/schedule",
        "课表日历（ICS）",
        "由 SIS 课表导出，需要教务凭据；无凭据时返回说明而不是 500。",
        "ics",
        lambda: "（ICS 文本，浏览器直接下载；此处不展示样例）",
    )
    return {"endpoints": endpoints, "count": len(endpoints)}


def _creds_summary() -> dict:
    """凭据状态一览（只报有无，绝不读出密码）。"""
    summary = {"sis": False}
    try:
        from westlake_survival.sso import read_credentials

        read_credentials()
        summary["sis"] = True
    except Exception:
        pass
    summary["all_set"] = summary["sis"]
    return summary


def _canvas_token_state() -> dict:
    """Canvas 令牌状态（只报来源有无，绝不读出令牌本体）。"""
    from westlake_survival.canvas.client import TOKEN_ENV_VAR, token_file_path

    env_value = os.environ.get(TOKEN_ENV_VAR)
    path = token_file_path()
    try:
        has_file = bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        has_file = False
    source = "环境变量" if env_value else ("本地文件" if has_file else "")
    return {
        "configured": bool(source),
        "source": source,
        "path": str(path),
        # 环境变量优先于文件；此时清文件不生效，页面要说明。
        "env_locked": bool(env_value),
    }


def _setup_context() -> dict:
    """设置页上下文：当前凭据状态 + 向导说明。"""
    return {"creds": _creds_summary(), "canvas": _canvas_token_state(), "error": None}


def _sis_context() -> dict:
    """学业页：24 块全量（课表/成绩/考试/评教 + 第二课堂 + 学业导师 + 其他申请 + 学籍档案 + 校园记录 + 社团与资助）。

    首块串行预热（确保 IAM 登录完成后共享会话），其余块 6 线程并行抓取；
    每块独立降级，单块失败不影响整页。
    """
    context: dict = {"blocks": {}}
    # 社团简介是随包内置的离线数据（改写自 WikiLake），无凭据也能读
    from westlake_survival import clubwiki

    context["club_wiki"] = clubwiki.catalog()

    def _sis_module(name: str):
        import importlib

        return importlib.import_module(f"westlake_survival.sis.{name}")

    def _cached_block(name: str, ttl: float, loader):
        """学业页大块短时缓存（导师名单 878KB、第二课堂 6 次跳转，重抓很贵）。

        TTL 内直接读磁盘；超过 TTL 或缓存损坏则重抓并回写。凭据/会话从不落盘。
        """
        from westlake_survival._cache import load_cached, save_cached

        cached = load_cached(f"sis/{name}.json", ttl)
        if cached is not None:
            return cached
        data = loader()
        try:
            save_cached(f"sis/{name}.json", data)
        except OSError:
            pass
        return data

    _TERM_ZH = {"Fall Term": "秋季学期", "Spring Term": "春季学期",
                "Summer Term": "夏季学期", "Winter Term": "冬季学期"}

    def _term_zh(term: str) -> str:
        """学期名归一：会话语言漂移时英文 Term 与中文季混排，统一显示中文。"""
        for en, zh in _TERM_ZH.items():
            if en in str(term or ""):
                return str(term).replace(en, zh)
        return str(term or "")

    def _clean_time(text: str) -> str:
        """课表时间清洗：去秒位（08:00:00 → 08:00）。"""
        return _re.sub(r"(\d{1,2}:\d{2}):\d{2}", "\\1", str(text or ""))

    def _clean_room(text: str) -> str:
        """地点清洗：逗号后补空格（E13-509,Yungu → E13-509, Yungu）。"""
        out = str(text or "")
        while ",," in out:
            out = out.replace(",,", ",")
        return out.replace(",", ", ")

    def _grades_with_stats():
        items = _sis_module("grades").grades()
        # GPA 估算：A=4.0 A-=3.7 B+=3.3 B=3.0 B-=2.7 C+=2.3 C=2.0 其余 0；仅统计有等级的课
        scale = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
                 "C+": 2.3, "C": 2.0, "C-": 1.7, "D": 1.0, "F": 0.0, "P": None, "NP": None}
        total_credits = 0.0
        total_points = 0.0
        by_term: dict[str, dict] = {}
        for g in items:
            grade = str(g.grade or "").strip()
            credits = 0.0
            try:
                credits = float(g.credits)
            except (TypeError, ValueError):
                pass
            point = scale.get(grade)
            term = _term_zh(g.term) or "未知学期"
            bucket = by_term.setdefault(term, {"credits": 0.0, "points": 0.0, "count": 0})
            bucket["count"] += 1
            if point is not None and credits:
                bucket["credits"] += credits
                bucket["points"] += point * credits
                total_credits += credits
                total_points += point * credits
        for term, b in by_term.items():
            b["gpa"] = round(b["points"] / b["credits"], 2) if b["credits"] else None

        def _term_order(term: str):
            """学期时间序：学年起始年 + 季节序（秋→冬→春→夏）。"""
            years = _re.findall(r"(\d{4})", str(term))
            start_year = int(years[0]) if years else 0
            season = next((rank for key, rank in
                           (("秋季", 0), ("冬", 1), ("春", 2), ("夏", 3))
                           if key in str(term)), 9)
            return (start_year, season)

        by_term = dict(sorted(by_term.items(), key=lambda kv: _term_order(kv[0])))
        return {
            "rows": [
                {"term": _term_zh(g.term), "name": g.course_title,
                 "grade": g.grade if str(g.grade or "").strip() else "—", "credits": g.credits}
                for g in items
            ],
            "total_courses": len(items),
            "total_credits": round(sum(
                float(g.credits) for g in items
                if str(g.credits or "").replace(".", "").isdigit()
            ), 1),
            "gpa_estimated": round(total_points / total_credits, 2) if total_credits else None,
            "gpa_note": "按 A=4.0/A-=3.7/B+=3.3/B=3.0… 估算，非官方算法",
            "by_term": [
                {"term": t, **b} for t, b in by_term.items()  # 已按 _term_order 排好
            ],
        }

    records = _sis_module("records")
    aid = _sis_module("aid")
    loaders: dict = {
        # 学业核心
        "schedule": lambda: [
            {"name": c.title, "teacher": c.teacher, "weekday": c.weekday,
             "time": _clean_time(f"{c.start_time}-{c.end_time}"), "location": _clean_room(c.room)}
            for c in _sis_module("client").get_schedule()
        ],
        "grades": _grades_with_stats,
        "exams": lambda: [
            {"course": e.course_title, "date": e.date, "time": e.time, "kind": e.exam_type,
             "room": e.venue, "seat": e.seat}
            for e in _sis_module("exams").exam_schedule()
        ],
        "evals": lambda: [
            {"name": e.course_title, "term": _term_zh(e.term), "period": e.period_raw}
            for e in _sis_module("evals").pending_evaluations()
        ],
        # 第二课堂（首页瓦片入口，左侧导航菜单里没有）
        "second_class": lambda: _cached_block(
            "second_class", 3600,
            lambda: _sis_module("second_class").second_classroom().to_dict(),
        ),
        # 学业导师（首页瓦片入口；两轮名单 + 分配结果）
        "advisor": lambda: _cached_block(
            "advisor", 6 * 3600,
            lambda: _sis_module("advisor").advising().to_dict(),
        ),
        # 其余申请类（学籍异动 / 困难认定 / 本博衔接 / 就业 / 学术进度）
        "other_apps": lambda: _cached_block(
            "other_applications", 3600,
            lambda: _sis_module("applications").other_applications().to_dict(),
        ),
        # 学籍档案
        "profile": lambda: _sis_module("profile").personal_info(),
        "academic": lambda: _sis_module("profile").academic_record().get("fields", {}),
        "extended": lambda: _sis_module("profile").extended_info().get("fields", {}),
        "registration": lambda: records.registration().to_dict(),
        # 校园记录
        "dorm": lambda: records.dormitory().to_dict(),
        "honors": lambda: [h.to_dict() for h in records.honors()],
        "vol_history": lambda: records.volunteer_history().to_dict(),
        "practice": lambda: [p.to_dict() for p in records.social_practice()],
        "leave": lambda: [l.to_dict() for l in records.leave_requests()],
        "discipline": lambda: [d.to_dict() for d in records.discipline_records()],
        "appointments": lambda: records.appointments().to_dict(),
        "leaving": lambda: records.leaving_check(),
        "source": lambda: records.source_info_status(),
        # 社团与资助
        "clubs": lambda: clubwiki.annotate([c.to_dict() for c in aid.my_clubs()]),
        "orgs": lambda: clubwiki.annotate([o.to_dict() for o in aid.student_orgs()]),
        "activities": lambda: [a.to_dict() for a in aid.student_activities()],
        "aid": lambda: {
            "loans": [r.to_dict() for r in aid.loans()],
            "loan_app": [r.to_dict() for r in aid.loan_application()],
            "repay": [r.to_dict() for r in aid.loan_repayments()],
            "outbound": [r.to_dict() for r in aid.outbound_programs()],
            "exchange": [r.to_dict() for r in aid.exchange_applications()],
            "jobs": [r.to_dict() for r in aid.study_jobs()],
            "claim_notice": aid.job_claim().get("notice", ""),
        },
    }

    def _run(key: str, loader):
        try:
            return key, loader()
        except Exception as exc:  # 每块独立降级
            return key, {"error": f"{exc.__class__.__name__}: {exc}"[:120]}

    # 预热：先串行跑第一块（完成 IAM 登录），再并行其余，避免并发登录竞态
    first_key = next(iter(loaders))
    context["blocks"][first_key] = dict([_run(first_key, loaders.pop(first_key))])[first_key]
    if loaders:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=6) as pool:
            for key, value in pool.map(lambda item: _run(*item), loaders.items()):
                context["blocks"][key] = value
    return context


def _canvas_context() -> dict:
    """Canvas 页：课程+成绩 / 公告 / 截止 / 考试 / 测验（令牌或统一会话，逐块降级）。"""
    context: dict = {"courses": [], "deadlines": [], "error": None}
    try:
        from westlake_survival.canvas.client import CanvasClient

        client = CanvasClient()
        courses = client.list_courses()

        def _clean_name(text: str) -> str:
            """课程名清洗：「|」分隔改「·」；中英边界补空格；压空白。"""
            out = str(text or "").replace("|", " · ")
            out = _re.sub(r"([A-Za-z])([一-鿿（])", r"\1 \2", out)
            out = _re.sub(r"([A-Za-z])([一-鿿（])", r"\1 \2", out)
            return " ".join(out.split())

        name_by_id = {c.id: _clean_name(c.name) for c in courses}
        context["courses"] = [
            {"name": _clean_name(c.name), "code": getattr(c, "code", ""), "id": c.id} for c in courses
        ]
        # 课程成绩（老师未发布时为 None，页面如实显示）
        try:
            context["grades"] = [
                {**row, "name": _clean_name(row.get("name", ""))}
                for row in client.course_grades()
            ]
        except Exception:
            context["grades"] = []
        # 每门课最新一条公告（并行抓，限前 6 门）
        def _latest_announcement(course_id):
            try:
                items = client.list_announcements(course_id)
                return items[0] if items else None
            except Exception:
                return None

        from concurrent.futures import ThreadPoolExecutor

        announcements = []
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for ann in pool.map(_latest_announcement, [c.id for c in courses[:6]]):
                    if ann is not None:
                        announcements.append({
                            "course": name_by_id.get(ann.course_id, str(ann.course_id)),
                            "title": ann.title,
                            "posted": ann.posted_at.strftime("%m-%d %H:%M") if ann.posted_at else "",
                            "url": ann.html_url,
                        })
        except Exception:
            announcements = []
        context["announcements"] = sorted(
            announcements, key=lambda a: a["posted"], reverse=True
        )
        # 考试/测验（库已有：quizzes + 日历 exam 事件）
        try:
            context["quizzes"] = [
                {"title": q.title, "course": name_by_id.get(q.course_id, str(q.course_id)),
                 "due": (q.due_at.strftime("%m-%d %H:%M") if q.due_at else ""),
                 "url": q.html_url}
                for q in client.quizzes()[:15]
            ]
        except Exception:
            context["quizzes"] = []
        try:
            context["exams"] = [
                {"title": e.title, "start": (e.start_at.strftime("%m-%d %H:%M") if e.start_at else ""),
                 "url": e.url}
                for e in client.exam_events()[:10]
            ]
        except Exception:
            context["exams"] = []
        context["deadlines"] = [
            {
                "title": a.name,
                "course": name_by_id.get(a.course_id, str(a.course_id)),
                "due": a.due_at.strftime("%m-%d %H:%M") if a.due_at else "",
                "url": a.html_url,
            }
            for a in client.upcoming_deadlines(limit=15)
        ]
        # Canvas 待办（users/self/todo）
        try:
            context["todo"] = [
                {
                    "course": _clean_name(row.course or ""),
                    "type": row.type,
                    "title": row.title or "",
                    "due": row.due_at.strftime("%m-%d %H:%M") if row.due_at else "",
                    "url": row.url or "",
                }
                for row in client.todo(limit=20)
            ]
        except Exception:
            context["todo"] = []
        # 课程内容：模块 / 文件 / 讨论（前 6 门并行，避免 10 门 × 3 接口拖慢）
        def _course_extra(course):
            extra = {"id": course.id, "name": name_by_id.get(course.id, str(course.id)),
                     "modules": [], "files": [], "discussions": []}
            try:
                extra["modules"] = client.modules(course.id)
            except Exception:
                pass
            try:
                extra["files"] = [
                    {"name": f.display_name or "", "size": f.size or 0,
                     "url": f.url or ""}
                    for f in client.list_files(course.id)[:5]
                ]
            except Exception:
                pass
            try:
                extra["discussions"] = client.discussions(course.id)[:3]
            except Exception:
                pass
            return extra

        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                context["course_content"] = list(pool.map(_course_extra, courses[:6]))
        except Exception:
            context["course_content"] = []
    except Exception as exc:  # pragma: no cover - 降级
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    return context


def _careers_context(keyword: str = "", category: str = "") -> dict:
    """招聘页：官网岗位 + 就业服务网三区块（公开数据）。"""
    context: dict = {"rows": [], "error": None, "keyword": keyword, "category": category,
                     "career_site": [], "career_site_error": None}
    module = _import_module("careers")
    if module is None or not hasattr(module, "positions"):
        context["error"] = "careers 模块不可用"
    else:
        try:
            items = module.positions(category=category or None, keyword=keyword or None, limit=60)
            context["rows"] = [
                {"title": p.title, "department": p.department, "type": p.job_type, "url": p.url}
                for p in items
            ]
        except Exception as exc:  # pragma: no cover
            context["error"] = f"{exc.__class__.__name__}: {exc}"[:120]
    site = _import_module("careersite")
    if site is not None and hasattr(site, "announcements"):
        try:
            context["career_site"] = [
                {"kind": it.kind_label, "title": it.title, "date": it.date,
                 "meta": " ".join(x for x in (it.status, it.time, it.venue) if x),
                 "url": it.url}
                for it in site.announcements(keyword=keyword or None)
            ]
        except Exception as exc:  # 就业网区块失败不拖垮官网岗位表
            context["career_site_error"] = f"{exc.__class__.__name__}: {exc}"[:120]
    return context


def _hpc_context() -> dict:
    """HPC 页：队列配置表 + 集群 + 入口（公开数据）。"""
    context: dict = {"queues": [], "clusters": [], "error": None}
    module = _import_module("hpc")
    if module is None or not hasattr(module, "overview"):
        context["error"] = "hpc 模块不可用"
        return context
    try:
        data = module.overview()
        context["clusters"] = data.clusters
        context["queues"] = [
            {"name": q.name, "nodes": q.nodes,
             "specs": [{"k": k, "v": v} for k, v in q.specs]}
            for q in data.queues
        ]
        context["portal"] = module.HPC_PORTAL
        context["main"] = module.HPC_MAIN
    except Exception as exc:  # pragma: no cover
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    # Westlake AI 网关（独立 try，失败不拖垮队列表）
    try:
        context["ai"] = module.ai_service()
        context["ai_probe"] = module.ai_gateway_probe()
    except Exception as exc:  # noqa: BLE001
        context["ai"] = None
        context["ai_probe"] = {"alive": False, "note": str(exc)[:80]}
    return context


def _mirrors_context() -> dict:
    """镜像站页：公开仓库目录（无凭据）。

    2026-10-27 审计：`/mirrors` 路由引用了这个函数但从未定义，页面一直 500
    （`NameError: _mirrors_context`）。模板要 ``repos`` 与 ``error`` 两个键。
    """
    context: dict = {"repos": [], "error": None}
    module = _import_module("mirrors")
    if module is None:
        context["error"] = "mirrors 模块不可用"
        return context
    try:
        context["repos"] = module.repos()
    except Exception as exc:  # noqa: BLE001 - 页面降级，不让整页 500
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    return context


def _wiki_context(query: str = "", category: str = "", deep: bool = False) -> dict:
    """百科页：WikiLake（学生自建）目录与检索。

    站点公开、无凭据；目录来自 sitemap 缓存，正文检索首次会抓全站（几秒）。
    """
    context: dict = {
        "refs": [],
        "results": [],
        "query": query,
        "category": category,
        "deep": deep,
        "cats": [],
        "error": None,
        "total": 0,
        "source_url": "https://wiki.mestlake.cc",
    }
    module = _import_module("wikilake")
    if module is None:
        context["error"] = "wikilake 模块不可用"
        return context
    try:
        refs = module.pages()
        context["total"] = len(refs)
        context["cats"] = sorted({ref.category for ref in refs})
        if query.strip():
            context["results"] = module.search(query.strip(), limit=20, deep=deep)
        elif category:
            context["refs"] = [ref for ref in refs if ref.category == category]
        else:
            context["refs"] = refs
    except Exception as exc:  # noqa: BLE001 - 页面降级，不让整页 500
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    return context


def _sport_context(day: str | None = None) -> dict:
    """场馆页：场景 × 当日场地可约状态 + 我的预约（独立正元系统）。

    体育场馆/游泳不在预约中心（``booking``），见 docs/sportvenue_notes.md。
    每次刷新要打 15 个场景接口，所以按日期做 10 分钟磁盘缓存。
    """
    from datetime import date as _date
    from datetime import timedelta

    from westlake_survival._cache import load_cached, save_cached

    context: dict = {"day": "", "scenes": [], "mine": [], "error": None, "note": ""}
    module = _import_module("sportvenue")
    if module is None:
        context["error"] = "sportvenue 模块不可用"
        return context
    when = day or (_date.today() + timedelta(days=1)).isoformat()
    context["day"] = when
    cached = load_cached(f"sport/page_{when}.json", 600)
    if cached is not None:
        context.update(cached)
        return context
    try:
        mine = module.my_reservations(limit=10)
        rows = []
        for scene in module.scenes():
            entry = {
                "name": scene.name,
                "uuid": scene.uuid,
                "sites": [],
                "total": 0,
                "bookable": 0,
                "reason": "",
            }
            try:
                sites = module.sites(scene, when)
            except Exception as exc:  # noqa: BLE001 - 单场景失败不影响整页
                entry["reason"] = f"查询失败：{exc.__class__.__name__}"
                rows.append(entry)
                continue
            entry["sites"] = [
                {
                    "name": site.name,
                    "location": site.location,
                    "bookable": site.bookable,
                    "reason": site.reason,
                }
                for site in sites
            ]
            entry["total"] = len(sites)
            entry["bookable"] = sum(1 for site in sites if site.bookable)
            reasons = {site.reason for site in sites if not site.bookable and site.reason}
            entry["reason"] = "；".join(sorted(reasons))[:80]
            rows.append(entry)
        payload = {
            "scenes": rows,
            "mine": [
                {
                    "date": str(row.get("reserveDate") or row.get("createTime") or ""),
                    "scene": str(row.get("sceneName") or ""),
                    "site": str(row.get("siteName") or ""),
                    "state": str(row.get("reserveState") or row.get("state") or ""),
                }
                for row in mine
            ],
            "error": None,
        }
        context.update(payload)
        save_cached(f"sport/page_{when}.json", payload)
    except Exception as exc:  # noqa: BLE001 - 页面降级
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:160]
    return context


def _finance_context() -> dict:
    """财务页：常用栏目的文档列表（公开）。"""
    context: dict = {"panels": [], "error": None}
    module = _import_module("finance")
    if module is None:
        context["error"] = "finance 模块不可用"
        return context
    try:
        shared = {a.url for a in module.articles("ywzn1/rcbx1.htm")}
        for title, path in (
            ("业务指南（报销操作）", "ywzn1/rcbx1.htm"),
            ("校内财务制度", "gzzd1/zmcwzd.htm"),
            ("科研经费管理", "ywzn1/kyjfgl.htm"),
            ("薪酬税务", "ywzn1/xcsw.htm"),
        ):
            items = module.articles(path, limit=20,
                                    exclude=None if path.endswith("rcbx1.htm") else shared)
            if items:
                context["panels"].append(
                    {"title": title, "entries": [{"t": i.title, "u": i.url} for i in items]}
                )
    except Exception as exc:  # pragma: no cover
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    return context


def _cached_json(name: str, ttl: float, loader):
    """通用短时磁盘缓存（门户站点图等慢查询）。"""
    from westlake_survival._cache import load_cached, save_cached

    cached = load_cached(name, ttl)
    if cached is not None:
        return cached
    data = loader()
    try:
        save_cached(name, data)
    except OSError:
        pass
    return data


def _reachable(url: str, timeout: float = 3.0) -> bool:
    """快速判断主机端口是否可达（内网服务离线时别让页面等满超时）。"""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _lib_context(query: str = "") -> dict:
    """图书馆页：书目检索 + 我的借阅 + 新书。

    2026-10-28 实测：老阿法迪 OPAC（``/opac/*``）整体下线，学校换成「阿法迪云
    eLibrary」新平台（``/page/login.jsp``，平台自有账号）。老接口全 404 时直接
    说明现状并跳过取数——尤其不能对已下线的 CAS 回调反复发起登录（有锁号风险）。
    """
    context: dict = {
        "query": query, "books": [], "loans": [], "new_books": [],
        "error": None, "loans_error": None, "new_error": None, "notice": None,
    }
    module = _import_module("lib")
    if module is None:
        context["error"] = "lib 模块不可用"
        return context
    opac = getattr(module, "OPAC_BASE", None)
    if not opac:
        try:
            from westlake_survival.lib.opac import OPAC_BASE as opac
        except Exception:
            opac = "http://172.16.10.223:8180/opac"
    try:
        from westlake_survival.lib.opac import detect_backend

        backend = detect_backend()
    except Exception:
        backend = None
    if backend and not backend.get("opac_alive"):
        context["notice"] = (
            "图书馆系统已迁移：老的 OPAC 检索 / 新书 / CAS 借阅接口整体下线"
            f"（{backend.get('detail', '')}）。"
            "新平台是「阿法迪云 eLibrary」，登录改成平台自有账号，本工具还没接新接口，"
            "所以这里暂时没有数据；查书与借阅请直接访问图书馆网站。"
        )
        return context
    if not _reachable(opac):
        message = "OPAC 仅校园网/VPN 内可达，请先连接学校 VPN"
        context["error"] = message
        context["loans_error"] = message
        context["new_error"] = message
        return context
    if query:
        try:
            context["books"] = [
                {
                    "title": b.title, "author": b.author, "call_no": b.call_no,
                    "location": b.location, "year": b.publish_year,
                    "status": b.holding_status, "url": b.detail_url,
                }
                for b in module.search(query)
            ]
        except Exception as exc:
            context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    try:
        context["loans"] = [
            {
                "title": loan.title, "due": loan.due_date, "renewable": loan.renewable,
                "location": loan.location, "barcode": loan.barcode,
            }
            for loan in module.my_loans()
        ]
    except Exception as exc:
        context["loans_error"] = f"{exc.__class__.__name__}: {exc}"[:120]
    try:
        context["new_books"] = [
            {"title": b.title, "author": b.author, "url": b.detail_url}
            for b in module.new_books(limit=12)
        ]
    except Exception as exc:
        context["new_error"] = f"{exc.__class__.__name__}: {exc}"[:120]
    return context


def _pms_context() -> dict:
    """自助文印页：网点列表 + 我的打印任务 + 用量统计（需校园网/VPN）。"""
    context: dict = {
        "stations": [], "jobs": [], "usage": [],
        "error": None, "jobs_error": None, "usage_error": None,
    }
    module = _import_module("pms")
    if module is None or not hasattr(module, "pms"):
        context["error"] = "pms 模块不可用"
        return context
    try:
        from westlake_survival.pms.client import resolve_base_url

        base_url = resolve_base_url()
    except Exception:
        base_url = "http://print.lib.westlake.edu.cn:9130"
    if not _reachable(base_url):
        message = "打印系统仅校园网/VPN 内可达，请先连接学校 VPN"
        context["error"] = message
        context["jobs_error"] = message
        context["usage_error"] = message
        return context
    client = module.pms()
    try:
        context["stations"] = [
            {
                "name": station.name, "campus": station.campus,
                "position": station.position or station.room_name,
                "status": station.status_text or ("空闲" if station.is_idle else ""),
                "papers": station.papers,
            }
            for station in client.list_stations()
        ]
    except Exception as exc:
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
    try:
        context["jobs"] = [
            {
                "name": job.name, "status": job.status_text or "—",
                "pages": job.pages, "copies": job.copies,
                "created": f"{job.created_date or ''} {job.created_time or ''}".strip(),
            }
            for job in client.list_print_jobs()
        ]
    except Exception as exc:
        context["jobs_error"] = f"{exc.__class__.__name__}: {exc}"[:120]
    try:
        kind_names = {1: "打印", 2: "复印", 3: "扫描"}
        context["usage"] = [
            {
                "kind": kind_names.get(item.type, str(item.type)),
                "times": item.times, "pages": item.pages, "cost": round(item.cost, 2),
            }
            for item in client.usage_stat()
        ]
    except Exception as exc:
        context["usage_error"] = f"{exc.__class__.__name__}: {exc}"[:120]
    return context


def _scholar_context() -> dict:
    """学术资源页上下文：校园状态 + 注册表 + CARSI 目录（可带 q 过滤）。"""
    from westlake_survival import scholar
    from westlake_survival._cache import load_json as _load

    context: dict = {"campus": {}, "dbs": [], "carsi": [], "carsi_query": "",
                     "carsi_fetched": "", "carsi_entry_cnki": "", "error": None}
    try:
        context["campus"] = scholar.campus_status().to_dict()
    except Exception as exc:  # 状态探测失败不拖垮整页
        context["campus"] = {"ip_authorized": False, "checked_at": "",
                             "evidence": f"探测失败：{exc.__class__.__name__}"}
    context["dbs"] = [vars(db) for db in scholar.databases()]
    context["carsi_entry_cnki"] = scholar.carsi_sso_entry("cnki")
    query = request.args.get("q", "").strip()
    if query:
        context["carsi_query"] = query
        try:
            context["carsi"] = scholar.carsi_catalog(query)
        except Exception as exc:
            context["error"] = f"CARSI 目录检索失败：{exc}"[:140]
    meta = _load("scholar/carsi_sps.json")
    if not isinstance(meta, dict):  # 在线缓存是裸数组；快照元数据在随包文件里
        try:
            import json as _json
            from pathlib import Path as _Path
            fixture = _Path(scholar.__file__).parent / "data" / "carsi_sps.json"
            meta = _json.loads(fixture.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    context["carsi_fetched"] = str(meta.get("fetched", ""))
    return context


def _scholar_doi_context() -> dict:
    """DOI 解析块上下文（/scholar/doi）。"""
    from westlake_survival import scholar

    doi = request.args.get("doi", "").strip()
    context: dict = {"doi_query": doi, "paper": None, "pdf_error": None}
    if not doi:
        return context
    try:
        context["paper"] = scholar.resolve_doi(doi).to_dict()
    except Exception as exc:
        context["pdf_error"] = f"解析失败：{exc}"[:200]
    return context





def _hosts_context() -> dict:
    """全量子站页：存活/不可达清单 + 已挖掘的栏目条目。"""
    module = _import_module("hosts")
    context: dict = {
        "error": None, "rows": [], "live": [], "dead": [], "mined": [],
        "stats": {"total": 0, "live": 0, "dead": 0, "covered": 0, "mined": 0, "items": 0},
    }
    if module is None:
        context["error"] = "hosts 模块不可用"
        return context
    try:
        rows = module.sweep()
    except Exception as exc:
        context["error"] = f"{exc.__class__.__name__}: {exc}"[:140]
        return context
    live = [row for row in rows if row.get("live")]
    dead = [row for row in rows if not row.get("live")]
    mined = []
    entries = []
    for row in live:
        data = None if row.get("sites_key") else module.cached_content(row["host"])
        if data and data.get("item_count"):
            mined.append(data)
        else:
            entries.append(row)
    context.update(
        rows=rows,
        live=entries,
        dead=dead,
        mined=mined,
        stats={
            "total": len(rows),
            "live": len(live),
            "dead": len(dead),
            "covered": sum(1 for row in rows if row.get("sites_key")),
            "mined": len(mined),
            "items": sum(item.get("item_count", 0) for item in mined),
        },
    )
    return context


def _services_context() -> dict:
    from westlake_survival.discovery import SERVICE_API_NOTES

    return {
        "registry": [
            {"host": h, "note": n, "mode": m,
             "api": SERVICE_API_NOTES.get(h, "")} for h, n, m in SERVICE_REGISTRY
        ],
        "covered": len(SERVICE_REGISTRY),
        "total": len(SERVICE_REGISTRY),
    }


def _clean_affair_name(text) -> str:
    """办事应用名清洗：中英边界补空格、压空白（源数据常中英连写）。"""
    import re as _re2

    out = str(text or "")
    out = _re2.sub(r"([一-鿿）])([A-Za-z])", r"\1 \2", out)
    out = _re2.sub(r"([A-Za-z])([一-鿿（])", r"\1 \2", out)
    return " ".join(out.split())


def _affairs_context() -> dict:
    """办事页上下文：我的待办/进行中 + 应用目录 + 常用入口；各块独立降级。"""
    context: dict = {
        "error": None, "apps": [], "links": [],
        "source_url": "one.westlake.edu.cn/taskcenter",
        "todo": [], "todo_error": None, "doing": [], "done": [], "cc": [],
        "portal": [], "portal_error": None,
    }
    tc = _import_module("taskcenter")
    if tc is not None:
        try:
            context["todo"] = [
                {"title": t.title, "department": t.department, "url": t.url} for t in tc.todo()
            ]
        except Exception as exc:
            context["todo_error"] = exc.__class__.__name__
        try:
            context["doing"] = [{"title": d.title, "status": d.status} for d in tc.doing()]
        except Exception:
            context["doing"] = []
        try:
            context["done"] = [{"title": d.title, "status": d.status} for d in tc.done()]
        except Exception:
            context["done"] = []
        try:
            context["cc"] = [{"title": c.title, "status": c.status} for c in tc.cc()]
        except Exception:
            context["cc"] = []
    module = _import_module("discovery")
    if module is not None and hasattr(module, "app_directory"):
        try:
            context["apps"] = [
                {"name": _clean_affair_name(a.name),
                 "department": a.department, "description": a.description}
                for a in module.app_directory()
            ]
        except Exception as exc:  # pragma: no cover - 数据源异常时降级
            context["error"] = f"办事大厅目录暂时不可用：{exc.__class__.__name__}"
    if module is not None and hasattr(module, "portal_services"):
        try:
            context["portal"] = _cached_json(
                "portal/services.json", 6 * 3600, module.portal_services
            )
        except Exception as exc:
            context["portal_error"] = f"{exc.__class__.__name__}"[:60]
    context["links"] = [
        {"title": "网上办事大厅", "url": module.TASKCENTER_BASE, "note": "待办/发起流程（统一认证登录）"}
        if module is not None else {},
        {"title": "HPC 门户", "url": getattr(module, "HPC_PORTAL", "https://hpc.westlake.edu.cn:9002/login.html"), "note": "集群作业/配额（统一密码）"},
        {"title": "预约中心", "url": getattr(module, "BOOKING_URL", "https://booking.westlake.edu.cn/yy-sys/"), "note": "场馆/会议室/资源预约"},
        {"title": "开源镜像站", "url": getattr(module, "MIRRORS_URL", "https://mirrors.westlake.edu.cn/"), "note": "pip/conda 换源"},
    ]
    return context


def _sites_context(refresh: bool = False) -> dict:
    """全站页上下文：37 站内容并行抓取，结果落盘缓存 10 分钟（卡顿修复）。

    首次全量实抓（含发现器/分页/手册树）约 10s；之后走 ``sites_page.json``
    缓存秒开，``?refresh=1`` 强制重抓。组内站点按 ``sites.SITE_ORDER``
    常用度排序。
    """
    module = _import_module("sites")
    if module is None:
        return {"error": "sites 模块不可用", "groups": [], "stats": {}}
    from concurrent.futures import ThreadPoolExecutor

    from westlake_survival._cache import load_json, save_json

    if not refresh:
        cached = load_json("sites_page.json")
        if cached and cached.get("context") and _time_mod.time() - cached.get("saved_at", 0) < 600:
            context = cached["context"]
            context["cached"] = True
            return context

    sites = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for content in pool.map(lambda k: module.site_content(k, limit=6), module.all_keys()):
            data = content.to_dict()
            # Jinja 坑（第四次）：dict 键名 items 命中方法，页面侧改名 entries
            data["sections"] = [
                {"label": sec["label"], "entries": sec["items"]} for sec in data["sections"]
            ]
            data["n_items"] = sum(len(sec["entries"]) for sec in data["sections"])
            data["n_sections"] = len(data["sections"])
            sites.append(data)
    groups: list[dict] = []
    order_map = getattr(module, "SITE_ORDER", {})
    for group in module.SITE_GROUPS:
        rows = [c for c in sites if c["group"] == group]
        if not rows:
            continue
        priority = {k: i for i, k in enumerate(order_map.get(group, []))}
        rows.sort(key=lambda c: priority.get(c["key"], 99))
        opened = next((i for i, c in enumerate(rows) if c["n_items"]), None)
        if opened is not None:
            rows[opened]["default_open"] = True
        groups.append({"name": group, "sites": rows})
    stats = {
        "total": len(sites),
        "with_items": sum(1 for c in sites if c["n_items"]),
        "entry_count": sum(c["n_items"] for c in sites),
        "section_count": sum(c["n_sections"] for c in sites),
    }
    context = {"error": None, "groups": groups, "stats": stats, "cached": False}
    try:
        save_json("sites_page.json", {"context": context, "saved_at": _time_mod.time()})
    except OSError:
        pass  # 缓存写失败不影响渲染
    return context


def _capabilities_context():
    """组装能力总览页上下文：CLI / MCP / WebUI 三组，含是否需要凭据。"""
    module = _import_module("capabilities")
    context: dict = {"error": None, "groups": [], "counts": {}, "items": []}
    if module is None or not hasattr(module, "as_dict"):
        context["error"] = "capabilities 模块不可用。"
        return context
    try:
        data = module.as_dict()
    except Exception as exc:  # pragma: no cover - 自省失败时降级
        context["error"] = f"能力清单生成失败：{exc.__class__.__name__}"
        return context
    items = data["items"]
    context["counts"] = data["counts"]
    context["items"] = items
    for kind, title in (("cli", "命令行（CLI）"), ("mcp", "MCP 工具"), ("web", "网页（WebUI）")):
        rows = [row for row in items if row["kind"] == kind]
        context["groups"].append({"title": title, "kind": kind, "rows": rows})
    return context


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
    # 离线 POI 数据集（可选）：存在就一起展示，缺失不影响公开地图部分。
    context["pois"] = []
    context["poi_total"] = 0
    context["poi_generated_at"] = ""
    try:
        from westlake_survival import mapdata

        if mapdata.dataset_available():
            dataset = mapdata.load_dataset()
            context["poi_total"] = len(dataset)
            context["poi_generated_at"] = dataset.generated_at
            context["pois"] = [
                {"name": hit.name, "brief": hit.brief(), "endpoint": hit.endpoint}
                for hit in dataset.records()[:200]
            ]
    except Exception:  # 数据集损坏不应影响整页
        logger.debug("地图数据集加载失败", exc_info=True)
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

    # 全站注入凭据状态：未配置时顶栏出引导横幅（用户主战场在网页，不在终端）。
    @app.context_processor
    def _inject_creds_status():
        creds = _creds_summary()
        return {"creds": creds, "needs_setup": not creds["sis"]}

    # -- 首页：context 快照仪表盘 ---------------------------------------- #
    @app.route("/")
    def index():
        # 第一次打开就把人送到「设置」：账号配置是启动后的第一件事。
        # 只想看公开功能（校历/班车/新闻/地图）的走 ?skip=1，或设置页的「先逛逛」。
        if not _creds_summary()["sis"] and request.args.get("skip") != "1":
            return redirect(url_for("setup_page"))
        try:
            # 单次构造 VERBOSE 快照：一次 I/O 拿全所有档位字段（terse 的日期 /
            # 周次、normal 的最近事件 / 下班车、verbose 的天气 / AQI / 作业），
            # 避免重复构造与重复加载校历 / 班车。verbose 字段无数据时模板显示
            # 「—」。
            data = _context_data("verbose")
            # 门户个人卡片（未读邮件/在借/待办）——失败静默降级
            portal_cards = {}
            portal_mod = _import_module("portal")
            if portal_mod is not None:
                try:
                    cards = portal_mod.fetch_cards()
                    portal_cards = {
                        "unread_email": cards.unread_email,
                        "borrowed_books": cards.borrowed_books,
                        "todo_pending": cards.todo_pending,
                        "todo_started": cards.todo_started,
                        "todo_done": cards.todo_done,
                    }
                except Exception:
                    portal_cards = {}
            data.setdefault("extras", {})["portal"] = portal_cards
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
        context["ics_urls"] = [
            {"title": "班车时刻", "url": request.host_url.rstrip("/") + "/ical/shuttle?days=30"},
            {"title": "本学期课表（需教务凭据）", "url": request.host_url.rstrip("/") + "/ical/schedule"},
        ]
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

    # -- 设置页（网页端账号配置）--------------------------------------------- #
    @app.route("/setup")
    def setup_page():
        return render_template("setup.html", **_setup_context())

    @app.route("/setup/api/stored")
    def setup_stored():
        """本机已存教务凭据（设置页「查看密码」用；等价密码管理器的显示功能）。

        服务只绑 127.0.0.1，与本机明文凭据文件同一信任域。Canvas 令牌只报
        有无与来源，不回显令牌本体。
        """
        canvas = _canvas_token_state()
        try:
            from westlake_survival.sso import read_credentials

            sid, password = read_credentials()
        except Exception:
            return {"configured": False, "canvas": canvas}
        return {"configured": True, "sid": sid, "password": password, "canvas": canvas}

    @app.route("/setup/api/canvas/clear", methods=["POST"])
    def setup_canvas_clear():
        """删除本地 Canvas 令牌，让 Canvas 回退统一密码（IAM CAS 会话）。"""
        from westlake_survival.canvas.client import clear_token_file

        removed = clear_token_file()
        state = _canvas_token_state()
        note = "已清除本地令牌" if removed else "本地本无令牌"
        if state["env_locked"]:
            note += "；环境变量 WESTLAKE_CANVAS_TOKEN 仍优先，需在启动环境里取消"
        return {"cleared": removed, "note": note, "canvas": state}

    @app.route("/setup/api/save", methods=["POST"])
    def setup_save():
        """保存凭据/令牌并（可选）验证。请求体含密码，只经 127.0.0.1，不落日志。

        两处与旧行为不同（2026-10-26 用户裁定 A+B）：
        * 验证未通过也落盘，响应里用 ``verified`` 如实区分「已验证 / 未验证已保存」；
        * 可一并保存或清除 Canvas 令牌，令牌可脱离学号密码单独提交。
        """
        from westlake_survival.setup_cmd import _handle_canvas_token, _persist, _probe_sis, _clear_canvas

        payload = request.get_json(silent=True) or {}
        sid = str(payload.get("sid") or "").strip()
        password = str(payload.get("password") or "")
        verify = bool(payload.get("verify", True))
        canvas_token = str(payload.get("canvas_token") or "").strip()
        clear_canvas = bool(payload.get("clear_canvas_token"))
        has_account = bool(sid and password)

        if not has_account and not canvas_token and not clear_canvas:
            return {"error": "学号与密码不能为空"}, 400

        result: dict = {}

        if has_account:
            sis_ok, sis_note = _probe_sis(sid, password) if verify else (False, "未验证（直接保存）")
            result["sid"] = sid
            stored_in = _persist(sid, password)
            result["sis"] = {
                "ok": sis_ok,
                "verified": bool(verify and sis_ok),
                "note": sis_note,
                "saved": True,
                "stored_in": stored_in,
            }

        if clear_canvas:
            result["canvas"] = {"cleared": _clear_canvas(), "note": "已清除本地令牌"}
        if canvas_token:
            saved, note = _handle_canvas_token(canvas_token, verify)
            entry = result.setdefault("canvas", {})
            entry.update({"ok": saved, "saved": saved, "note": note})
        if "canvas" in result:
            result["canvas"]["state"] = _canvas_token_state()

        return result

    # -- 学院官网聚合页 ------------------------------------------------------ #
    @app.route("/sites")
    def sites_page():
        from flask import request as _rq

        context = _sites_context(refresh=_rq.args.get("refresh") == "1")
        if context.get("error"):
            return render_template("error.html", message=context["error"]), 503
        return render_template("sites.html", **context)

    @app.route("/api/sites/detail")
    def api_sites_detail():
        """条目详情（深挖层 2）：?url= 站内页面 -> 标题/摘要/附件。"""
        from flask import request

        module = _import_module("sites")
        url = (request.args.get("url") or "").strip()
        if module is None or not url:
            return {"error": "缺 ?url= 参数"}, 400
        try:
            return module.site_detail(url)
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响列表
            return {"error": f"{exc.__class__.__name__}: {exc}"[:160]}, 502

    @app.route("/vpn")
    def vpn_page():
        """SSL VPN 手动登录页：状态卡 + 拉起登录窗口按钮 + 资源列表。"""
        module = _import_module("vpn")
        st = {"logged_in": False, "code": "", "message": "vpn 模块不可用"}
        if module is not None:
            st = module.status()
        return render_template("vpn.html", status=st)

    @app.route("/vpn/api/login", methods=["POST"])
    def vpn_api_login():
        """拉起 `westlake vpn login` 子进程（有头浏览器，本人输验证码）。"""
        import subprocess
        import sys

        try:
            subprocess.Popen(
                [sys.executable, "-m", "westlake_survival", "vpn", "login", "--wait", "600"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {"ok": True, "message": "登录窗口已打开：在弹出的浏览器里输入验证码完成登录"}
        except Exception as exc:  # noqa: BLE001 - 拉起失败如实回报
            return {"ok": False, "message": f"{exc.__class__.__name__}: {exc}"[:120]}, 500

    @app.route("/vpn/api/status")
    def vpn_api_status():
        """轮询会话状态；活则顺带资源列表。"""
        module = _import_module("vpn")
        if module is None:
            return {"logged_in": False, "message": "vpn 模块不可用"}, 503
        st = module.status()
        res: list = []
        if st.get("logged_in"):
            try:
                res = [{"title": r.get("title", ""), "url": r.get("url", "")}
                       for r in (module.resources() or [])[:40]]
            except Exception as exc:  # noqa: BLE001 - 资源失败不影响状态
                st["resources_error"] = f"{exc.__class__.__name__}: {exc}"[:100]
        st["resources"] = res
        return st

    @app.route("/schools")
    def schools_page():
        module = _import_module("schools")
        cards = []
        if module is not None:
            for key, (name, base, _kind) in module.SCHOOLS.items():
                card = {"key": key, "name": name, "url": base, "items": [], "error": None}
                try:
                    card["entries"] = [
                        {"t": art.title, "u": art.url, "d": art.date} for art in module.news(key, limit=5)
                    ]
                except Exception as exc:  # 单院失败不拖垮其余
                    card["error"] = exc.__class__.__name__
                cards.append(card)
        return render_template("schools.html", cards=cards)

    # -- 理论科学研究院页 ---------------------------------------------------- #
    @app.route("/institute")
    def institute_page():
        context: dict = {"panels": [], "error": None}
        module = _import_module("institute")
        if module is None:
            context["error"] = "institute 模块不可用"
            return render_template("institute.html", **context)
        for title, path in module.LIST_COLUMNS:
            try:
                items = module.articles(path, limit=12)
                context["panels"].append(
                    {"title": title, "entries": [{"t": a.title, "u": a.url} for a in items]}
                )
            except Exception:  # 单栏目失败不影响其余
                continue
        if not context["panels"]:
            context["error"] = "栏目均不可用（网络或结构变化）"
        return render_template("institute.html", **context)

    # -- HPC / 财务 / 镜像 / 服务注册表 -------------------------------------- #
    @app.route("/hpc")
    def hpc_page():
        return render_template("hpc.html", **_hpc_context())

    @app.route("/finance")
    def finance_page():
        return render_template("finance.html", **_finance_context())

    @app.route("/mirrors")
    def mirrors_page():
        return render_template("mirrors.html", **_mirrors_context())

    @app.route("/wiki")
    def wiki_page():
        return render_template(
            "wikilake.html",
            **_wiki_context(
                query=request.args.get("q", ""),
                category=request.args.get("cat", "").strip(),
                deep=request.args.get("deep") in {"1", "true", "on"},
            ),
        )

    @app.route("/lib")
    def lib_page():
        return render_template("lib.html", **_lib_context(request.args.get("q", "").strip()))

    @app.route("/pms")
    def pms_page():
        return render_template("pms.html", **_pms_context())

    # -- 场馆（体育/游泳，独立正元系统） ------------------------------------- #
    @app.route("/sport")
    def sport_page():
        day = request.args.get("date", "").strip()
        return render_template("sport.html", **_sport_context(day or None))

    # -- 学术资源页（订阅库 / CARSI / DOI） ---------------------------------- #
    @app.route("/scholar")
    def scholar_page():
        return render_template("scholar.html", **_scholar_context())

    @app.route("/scholar/doi")
    def scholar_doi_page():
        context = _scholar_context()
        context.update(_scholar_doi_context())  # DOI 块的键优先生效
        return render_template("scholar.html", **context)

    @app.route("/scholar/doi.pdf")
    def scholar_doi_pdf():
        from westlake_survival import scholar

        doi = request.args.get("doi", "").strip()
        if not doi:
            return {"error": "doi 参数不能为空"}, 400
        import tempfile
        from flask import send_file

        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            path = scholar.fetch_pdf(doi, out=handle.name)
        except Exception as exc:
            return {"error": str(exc)[:300]}, 502
        return send_file(path, as_attachment=True,
                         download_name=path.name, mimetype="application/pdf")

    @app.route("/api/scholar/doi")
    def api_scholar_doi():
        """DOI 解析 JSON（Agent 友好）：题录 + OA/出版社 PDF 线索 + 校园网提示。"""
        from westlake_survival import scholar

        doi = request.args.get("doi", "").strip()
        if not doi:
            return {"error": "doi 参数不能为空"}, 400
        try:
            return scholar.resolve_doi(doi).to_dict()
        except Exception as exc:
            return {"error": str(exc)[:300]}, 502

    @app.route("/services")
    def services_page():
        return render_template("services.html", **_services_context())

    @app.route("/hosts")
    def hosts_page():
        return render_template("hosts.html", **_hosts_context())

    # -- 学业页（SIS） ------------------------------------------------------ #
    @app.route("/sis")
    def sis_page():
        return render_template("sis.html", **_sis_context())

    # -- Canvas 页 ---------------------------------------------------------- #
    @app.route("/canvas")
    def canvas_page():
        return render_template("canvas.html", **_canvas_context())

    # -- 招聘页 -------------------------------------------------------------- #
    @app.route("/careers")
    def careers_page():
        return render_template(
            "careers.html",
            **_careers_context(
                keyword=request.args.get("q", ""),
                category=request.args.get("category", ""),
            ),
        )

    # -- 服务普查 API（按钮触发，避免拖慢页面）-------------------------------- #
    @app.route("/api/services/scan")
    def services_scan_api():
        module = _import_module("discovery")
        if module is None:
            return {"error": "discovery 模块不可用"}, 503
        hosts = request.args.get("hosts", "")
        host_list = [h.strip() for h in hosts.split(",") if h.strip()] or None
        results = module.subdomain_census(host_list, timeout=4.0)
        return {
            "alive": [
                {"host": r.host, "status": r.status, "title": r.title}
                for r in results
                if r.alive
            ],
            "total": len(results),
        }

    # -- 办事大厅页 -------------------------------------------------------- #
    @app.route("/affairs")
    def affairs_page():
        return render_template("affairs.html", **_affairs_context())

    # -- 能力总览页 -------------------------------------------------------- #
    @app.route("/capabilities")
    def capabilities_page():
        context = _capabilities_context()
        try:
            context["api_endpoints"] = _api_doc_context()["endpoints"]
        except Exception:  # 接口样例失败不影响能力页
            context["api_endpoints"] = []
        return render_template("capabilities.html", **context)

    @app.route("/api/capabilities")
    def capabilities_api():
        module = _import_module("capabilities")
        if module is None:
            return {"error": "capabilities 模块不可用"}, 503
        return module.as_dict()

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

    # --（API 说明页已并入 /capabilities；裸接口 /api/* 与 /ical/* 保留）-- #

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
