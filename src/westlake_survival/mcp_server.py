"""MCP（Model Context Protocol）stdio 服务器：把西湖大学数据以只读工具暴露给 AI 客户端。

零第三方依赖：只用标准库实现 MCP over stdio 的最小面（JSON-RPC 2.0 行协议），
不引入 ``mcp`` / ``anyio`` 等包。协议语义对标常见校园 CLI 的 MCP server
（只读工具、stdio、无写操作），实现为自研。

协议实现
========
* 传输：stdin 一行一条 JSON 消息，stdout 一行一条 JSON 响应；日志一律走
  stderr（**stdout 只放协议数据**，否则会污染客户端解析）。
* 方法：``initialize`` 握手、``notifications/initialized``（通知，忽略）、
  ``tools/list``、``tools/call``、``ping``；未知方法返回标准 JSON-RPC 错误
  （``-32601 Method not found``）。
* 错误码：``-32700`` 解析错误 / ``-32600`` 非法请求 / ``-32601`` 方法不存在 /
  ``-32602`` 参数错误 / ``-32603`` 内部错误。
* 工具执行失败**不走 JSON-RPC 错误**，而是返回 ``isError: true`` 的
  ``content``（MCP 约定），因此客户端能拿到可读的中文报错文本。
  ``tools/call`` 里的未知工具名属协议层错误，返回 ``-32602``。
* 检测到 stdin EOF 即退出；每条响应写完立即 flush。

只读工具（每个对应库内一个公开 API，参数 0~2 个，全部异常兜底不崩进程）
=======================================================================
``sis_schedule`` / ``sis_grades`` / ``sis_exams`` / ``sis_evals_pending`` /
``calendar_today`` / ``calendar_week`` / ``transit_next`` / ``news_latest`` /
``program_overview`` / ``program_curriculum`` / ``program_majors`` /
``program_plan`` / ``program_courses`` / ``program_course_search`` /
``events_upcoming`` / ``research_latest`` / ``site_search`` / ``faculty_search`` /
``campus_dining`` / ``campus_housing`` / ``campus_map`` / ``affairs_apps`` / ``contact_info`` / ``context_snapshot`` /
``scholar_databases`` / ``scholar_resolve_doi`` / ``scholar_campus``（学术资源）/
``canvas_deadlines``；另有写操作工具 ``canvas_submit``（交作业，缺省只预检，
``confirm=true`` 才真正提交）。

所有工具惰性 import 各自业务模块（缺依赖/缺模块时返回 ``isError``），
输出统一转成紧凑 JSON 文本（dataclass 优先用其 ``to_dict``，否则递归序列化）。

运行
====
::

    python -m westlake_survival.mcp_server

ZCode / Claude Desktop 等 MCP 客户端接入配置（把路径换成本机实际值）::

    {
      "mcpServers": {
        "westlake": {
          "command": "D:/westlake_survival/.venv/Scripts/python.exe",
          "args": ["-m", "westlake_survival.mcp_server"],
          "env": {
            "PYTHONPATH": "D:/westlake_survival/src",
            "WESTLAKE_CANVAS_TOKEN": ""
          }
        }
      }
    }

``WESTLAKE_CANVAS_TOKEN`` 可选（``canvas_deadlines`` / ``canvas_submit`` 需要；
缺省从 ``~/.westlake_survival/canvas_token.txt`` 首行读取，都没有时这两个工具
返回获取引导）。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, time
from enum import Enum
from typing import Any, Iterable

from westlake_survival._version import __version__

logger = logging.getLogger("westlake_survival.mcp")

#: 服务器名（``initialize`` 的 ``serverInfo.name``）。
SERVER_NAME = "westlake_survival"

#: 兜底协议版本；客户端在 ``initialize.params.protocolVersion`` 里给了版本时回显它，
#: 最大化与各版本客户端的兼容性。
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

#: 中文星期名（周一 .. 周日）。
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: 校区取值（与 :data:`westlake_survival.campus.CAMPUS_CHOICES` 同口径）。
_CAMPUS_ENUM = ("云谷", "云栖", "铜鉴湖")


class ToolHint(Exception):
    """工具返回的"引导信息"（非错误）：以正常 ``content`` 文本呈现。

    目前只有 ``canvas_deadlines`` 缺 token 时用——给客户端一段可照做的配置
    引导，而不是一个红字错误。
    """


# --------------------------------------------------------------------------- #
# JSON-RPC 错误码
# --------------------------------------------------------------------------- #
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# --------------------------------------------------------------------------- #
# 序列化：任意对象 → JSON 可序列化结构
# --------------------------------------------------------------------------- #
def _to_plain(value: Any) -> Any:
    """把库内返回的对象递归转成 JSON 可序列化结构。

    优先级：枚举→``.value``（必须先于标量，见下）、None/标量原样、日期时间→
    ISO 字符串、``to_dict()``→递归、dataclass→``asdict`` 后递归、容器→逐项
    递归，最后兜底 ``str()``。
    """
    # 枚举先于标量判断：``class Campus(str, Enum)`` 也是 ``str`` 实例，
    # 若被标量分支拦下，``json.dumps`` 会输出 ``"Campus.YUNGU"`` 而非 ``"云谷"``。
    if isinstance(value, Enum):
        return _to_plain(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    # 库内模型的 ``to_dict()`` 是权威序列化口径，优先于泛化的 asdict 兜底。
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _to_plain(to_dict())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _to_plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_plain(item) for item in value]
    return str(value)


def _dumps(value: Any) -> str:
    """紧凑 JSON 文本（单行，无多余空白）。"""
    return json.dumps(_to_plain(value), ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# 参数取值辅助（把类型/范围错误变成可读 ValueError → isError 文本）
# --------------------------------------------------------------------------- #
def _opt_int(args: dict, key: str, default: int, *, minimum: int | None = None,
             maximum: int | None = None) -> int:
    """从 ``args`` 取整数参数 ``key``（缺省 ``default``），越界/类型错抛 ValueError。"""
    raw = args.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"参数 {key} 必须是整数，得到 {raw!r}")
    value = int(raw)
    if raw != value:
        raise ValueError(f"参数 {key} 必须是整数，得到 {raw!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"参数 {key} 必须 >= {minimum}，得到 {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"参数 {key} 必须 <= {maximum}，得到 {value}")
    return value


def _opt_str(args: dict, key: str) -> str | None:
    """从 ``args`` 取字符串参数；缺省/空串/非字符串返回 ``None``。"""
    raw = args.get(key)
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    return raw or None


def _opt_keyword(args: dict, key: str) -> str | None:
    """取课程/作业/主题这类「id 或关键词」参数。

    客户端常把纯数字 id 按整数传进来，这里一并接受，统一转成字符串交给
    ``find_*`` 方法处理。
    """
    raw = args.get(key)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, str):
        return raw.strip() or None
    return None


# --------------------------------------------------------------------------- #
# 工具实现（每个惰性 import 对应业务模块；抛异常即 isError）
# --------------------------------------------------------------------------- #
def _tool_sis_schedule(args: dict) -> Any:
    """本学期课表节次。"""
    from westlake_survival.sis import get_schedule

    return [session.to_dict() for session in get_schedule()]


def _tool_sis_grades(args: dict) -> Any:
    """全部学期成绩。"""
    from westlake_survival.sis import grades

    return [grade.to_dict() for grade in grades()]


def _tool_sis_exams(args: dict) -> Any:
    """当前学期考试安排。"""
    from westlake_survival.sis import exam_schedule

    return [slot.to_dict() for slot in exam_schedule()]


def _tool_sis_evals_pending(args: dict) -> Any:
    """未完成的评教任务。"""
    from westlake_survival.sis import pending_evaluations

    return [task.to_dict() for task in pending_evaluations()]


def _tool_sis_volunteer_history(args: dict) -> Any:
    """志愿服务历史（官方录入 + 自主提交，含总时长）。"""
    from westlake_survival.sis.records import volunteer_history

    return volunteer_history().to_dict()


def _tool_sis_registration(args: dict) -> Any:
    """学期注册缴费状态（个人信息 + 缴费提示）。"""
    from westlake_survival.sis.records import registration

    return registration().to_dict()


def _tool_sis_appointments(args: dict) -> Any:
    """本周心理预约（周历范围 + 已占用时段）。"""
    from westlake_survival.sis.records import appointments

    return appointments().to_dict()


def _tool_sis_clubs(args: dict) -> Any:
    """我的社团（学年 / 社团 / 发起人 / 人数）。"""
    from westlake_survival.sis.aid import my_clubs

    return [org.to_dict() for org in my_clubs()]


def _tool_sis_second_class(args: dict) -> Any:
    """第二课堂成绩单（5 个维度 + 每项要求进度）。"""
    from westlake_survival.sis.second_class import second_classroom

    return second_classroom().to_dict()


def _tool_sis_advisor(args: dict) -> Any:
    """学业导师：分配结果 + 各轮名单（配额 / 余量 / 志愿人数）。"""
    from westlake_survival.sis.advisor import advising

    return advising().to_dict()


def _tool_sis_other_applications(args: dict) -> Any:
    """学籍异动流程 / 困难认定 / 本博衔接 / 就业四类申请状态。"""
    from westlake_survival.sis.applications import other_applications

    return other_applications().to_dict()


def _tool_sites_index(args: dict) -> Any:
    """全部已接入站点索引（key/名称/分组/URL）。"""
    from westlake_survival.sites import sites_index

    return sites_index()


def _tool_hosts_inventory(args: dict) -> Any:
    """全量子域清单：存活/不可达、标题、是否人工配置。"""
    from westlake_survival.hosts import sweep

    rows = sweep()
    live = [row for row in rows if row.get("live")]
    return {
        "total": len(rows),
        "live": len(live),
        "dead": len(rows) - len(live),
        "hosts": rows,
    }


def _tool_hosts_content(args: dict) -> Any:
    """某子域的栏目与条目（通用挖掘，缓存 24 小时）。"""
    from westlake_survival.hosts import content

    host = _opt_str(args, "host") or ""
    if not host:
        raise ToolHint("需要 host 参数，如 host=career")
    return content(host)


def _tool_site_content(args: dict) -> Any:
    """取一个站点的栏目与条目（key 见 sites_index）。"""
    key = _opt_str(args, "key") or ""
    from westlake_survival.sites import site_content

    return site_content(key, limit=int(args.get("limit") or 8)).to_dict()


def _tool_site_detail(args: dict) -> Any:
    """抓一条站内页面详情：标题/正文摘要/附件下载（仅 *.westlake.edu.cn）。"""
    url = _opt_str(args, "url") or ""
    from westlake_survival.sites import site_detail

    return site_detail(url)


def _tool_vpn_status(args: dict) -> Any:
    """SSL VPN 会话状态与已发布内网资源（需在 /vpn 页手动登录过）。"""
    from westlake_survival.vpn import resources, status

    st = status()
    if st.get("logged_in"):
        try:
            st["resources"] = [
                {"title": r.get("title", ""), "url": r.get("url", "")} for r in resources()[:40]
            ]
        except Exception as exc:  # noqa: BLE001 - 资源失败不影响状态
            st["resources_error"] = f"{exc.__class__.__name__}: {exc}"[:100]
    return st


def _tool_hpc_ai(args: dict) -> Any:
    """Westlake AI 大模型网关：地址/领令牌/模型清单 + 网关存活探测。"""
    from westlake_survival.hpc import ai_gateway_probe, ai_service

    info = ai_service()
    info["probe"] = ai_gateway_probe()
    return info


def _tool_sis_statuses(args: dict) -> Any:
    """离校检查 / 生源确认 / 工时申报三类状态提示。"""
    from westlake_survival.sis.aid import job_claim
    from westlake_survival.sis.records import leaving_check, source_info_status

    return {
        "leaving_check": leaving_check(),
        "source_info": source_info_status(),
        "job_claim": job_claim(),
    }


def _tool_calendar_today(args: dict) -> Any:
    """今天的日期 / 学期 / 周次 / 当日校历事件。"""
    from westlake_survival.calendar import AcademicCalendar

    calendar = AcademicCalendar.load()
    today = date.today()
    semester = calendar.current(today)
    payload: dict[str, Any] = {
        "date": today.isoformat(),
        "weekday": _WEEKDAY_CN[today.weekday()],
        "semester": None,
        "week": None,
        "is_teaching_day": None,
        "is_holiday": None,
        "events": [],
    }
    if semester is None:
        return payload
    payload["semester"] = semester.name
    payload["week"] = semester.week_of(today)
    payload["is_teaching_day"] = semester.is_teaching_day(today)
    payload["is_holiday"] = semester.is_holiday(today)
    payload["events"] = [
        {"title": e.title, "start": e.start.isoformat(),
         "end": e.end.isoformat() if e.end else None}
        for e in semester.events
        if e.covers(today)
    ]
    return payload


def _tool_calendar_week(args: dict) -> Any:
    """第 N 周的起止日期（缺省取当前周）。"""
    from westlake_survival.calendar import AcademicCalendar

    calendar = AcademicCalendar.load()
    today = date.today()
    semester = calendar.current(today)
    if semester is None and calendar.semesters:
        semester = calendar.semesters[-1]
    if semester is None:
        raise ValueError("未找到任何学期数据，无法换算周次")

    total = semester.teaching_weeks()
    raw = args.get("week")
    if raw is None:
        week = semester.week_of(today)
        if week is None:
            raise ValueError(
                f"今天不在 {semester.name} 的教学周内，请显式指定 week（1..{total}）"
            )
    else:
        week = _opt_int(args, "week", 1, minimum=1, maximum=max(1, total))
    return {
        "semester": semester.name,
        "week": week,
        "total_weeks": total,
        "start": semester.date_of(week, 1).isoformat(),
        "end": semester.date_of(week, 7).isoformat(),
    }


def _tool_transit_next(args: dict) -> Any:
    """下一批发车时刻（可按校区过滤）。"""
    from westlake_survival.transit import Campus, transit

    campus_name = _opt_str(args, "campus")
    campus = Campus(campus_name) if campus_name else None
    limit = _opt_int(args, "limit", 3, minimum=1, maximum=20)
    departures = transit().next_departures(campus=campus, limit=limit)
    return [
        {
            "time": time_str,
            "campus": table.campus.value,
            "day_kind": table.day_kind.value,
            "direction": table.direction_note,
        }
        for table, time_str in departures
    ]


def _tool_news_latest(args: dict) -> Any:
    """西湖新闻最新条目。"""
    from westlake_survival.news import latest

    limit = _opt_int(args, "limit", 10, minimum=1, maximum=50)
    return [
        {
            "title": item.title,
            "category": item.category,
            "date": item.date.isoformat() if item.date else None,
            "url": item.url,
        }
        for item in latest(limit=limit)
    ]


def _section_plain(section: Any) -> dict:
    """把 :class:`westlake_survival.program.ProgramSection` 压成纯数据。"""
    out: dict[str, Any] = {
        "key": section.key,
        "title": section.title,
        "content": section.content_text,
    }
    if section.table is not None:
        out["table"] = {
            "name": section.table.name,
            "headers": section.table.headers,
            "rows": [
                {"name": row.name, "items": row.items} for row in section.table.rows
            ],
        }
    return out


def _tool_program_overview(args: dict) -> Any:
    """本科培养理念：培养目标与培养特色（官网公开版）。"""
    from westlake_survival.program import overview

    lang = _opt_str(args, "lang") or "zh"
    data = overview(lang)
    return {
        "lang": data.lang,
        "url": data.url,
        "goal": data.goal.content_text,
        "features": [{"title": f.title, "content": f.content_text} for f in data.features],
    }


def _tool_program_curriculum(args: dict) -> Any:
    """本科课程体系：核心课程 / 通识课程表 / 专业课程等栏目（官网公开版）。"""
    from westlake_survival.program import curriculum

    lang = _opt_str(args, "lang") or "zh"
    data = curriculum(lang)
    return {
        "lang": data.lang,
        "url": data.url,
        "sections": [_section_plain(section) for section in data.sections],
    }


def _tool_program_majors(args: dict) -> Any:
    """本科专业设置：8 个专业总览与分专业介绍（官网公开版）。"""
    from westlake_survival.program import majors

    lang = _opt_str(args, "lang") or "zh"
    data = majors(lang)
    return {
        "lang": data.lang,
        "url": data.url,
        "summary": data.summary,
        "majors": [
            {
                "group": major.group,
                "name": major.name,
                "value": major.value,
                "sections": [_section_plain(section) for section in major.sections],
            }
            for major in data.majors
        ],
    }


def _tool_program_courses(args: dict) -> Any:
    """通识课程目录（三类，含学分/开课学期/先修/教师/可选简介）。"""
    from westlake_survival.program import common_courses

    category = _opt_str(args, "category")
    keyword = _opt_str(args, "keyword")
    detail = bool(args.get("detail"))
    catalog = common_courses(category=category, keyword=keyword)
    courses = []
    for course in catalog.courses:
        item: dict[str, Any] = {
            "title": course.title,
            "category": course.category,
            "subject": course.subject,
            "credits": course.credits,
            "semester": course.semester,
        }
        if course.prerequisite:
            item["prerequisite"] = course.prerequisite
        if course.teachers:
            item["teachers"] = [teacher.name for teacher in course.teachers]
        if detail:
            item["description"] = course.description_text
        courses.append(item)
    return {
        "url": catalog.url,
        "count": len(courses),
        "notices": catalog.notices,
        "courses": courses,
    }


def _tool_program_course_search(args: dict) -> Any:
    """跨源课程搜索：通识目录 + 8 个专业培养方案的课程表。"""
    from westlake_survival.program import course_search

    keyword = _opt_str(args, "keyword") or ""
    include_plans = not bool(args.get("common_only"))
    hits = course_search(keyword, include_major_plans=include_plans)
    detail = bool(args.get("detail"))
    return {
        "keyword": keyword,
        "count": len(hits),
        "hits": [
            {
                "title": hit.title,
                "credits": hit.credits,
                "source": hit.source,
                "prerequisite": hit.prerequisite,
                **({"description": hit.description_text} if detail else {}),
            }
            for hit in hits
        ],
    }


def _tool_program_plan(args: dict) -> Any:
    """专业培养方案：学分要求 + 课程表（含先修课程与可选简介）。"""
    from westlake_survival.program import major_plans

    major = _opt_str(args, "major")
    detail = bool(args.get("detail"))
    catalog = major_plans(major)
    selected = catalog.match(major) if major else catalog.majors
    if not selected:
        selected = catalog.majors

    def _course(course: Any) -> dict:
        out: dict[str, Any] = {
            "name": course.name,
            "credits": course.credits,
        }
        if course.group:
            out["group"] = course.group
        if course.prerequisite:
            out["prerequisite"] = course.prerequisite
        if course.teachers:
            out["teachers"] = course.teachers
        if detail:
            out["description"] = course.description_text
        return out

    return {
        "url": catalog.url,
        "majors": [
            {
                "name": plan.name,
                "total_credits": plan.total_credits,
                "course_count": plan.course_count,
                "intro": [{"title": s.title, "content": s.content_text} for s in plan.intro],
                "requirements": [
                    {
                        "title": req.title,
                        "credits": req.credits,
                        "note": req.note,
                        "url": req.url,
                        "courses": [_course(course) for course in req.courses],
                    }
                    for req in plan.requirements
                ],
                "warn_text": plan.warn_text,
            }
            for plan in selected
        ],
    }


def _tool_events_upcoming(args: dict) -> Any:
    """未来 N 天的活动预告。"""
    from westlake_survival.events import upcoming

    days = _opt_int(args, "days", 14, minimum=0, maximum=90)
    return [
        {
            "title": item.title,
            "date": item.date.isoformat(),
            "time_range": item.time_range,
            "venue": item.venue,
            "organizer": item.organizer,
            "event_type": item.event_type,
            "url": item.url,
        }
        for item in upcoming(days=days)
    ]


def _tool_research_latest(args: dict) -> Any:
    """科研进展最新条目。"""
    from westlake_survival.research import latest

    limit = _opt_int(args, "limit", 10, minimum=1, maximum=50)
    return [
        {
            "title": item.title,
            "category": item.category,
            "date": item.date.isoformat() if item.date else None,
            "url": item.url,
        }
        for item in latest(limit=limit)
    ]


def _tool_site_search(args: dict) -> Any:
    """官网全站搜索。"""
    from westlake_survival.search import search

    query = _opt_str(args, "query")
    if not query:
        raise ValueError("参数 query 不能为空")
    page = _opt_int(args, "page", 1, minimum=1)
    result = search(query, page=page)
    return {
        "query": query,
        "page": result.page,
        "page_count": result.page_count,
        "total": result.total,
        "hits": [
            {
                "title": hit.clean_title,
                "url": hit.url,
                "date": hit.date.isoformat() if hit.date else None,
                "desc": hit.clean_desc,
            }
            for hit in result.hits
        ],
    }


def _tool_faculty_search(args: dict) -> Any:
    """教师名录检索（按学院 / 关键词）。"""
    from westlake_survival.faculty import members

    school = _opt_str(args, "school")
    keyword = _opt_str(args, "keyword")
    return [
        {
            "name": member.name,
            "name_en": member.name_en,
            "school": member.school,
            "subject": member.subject,
            "lab": member.lab,
            "url": member.url,
        }
        for member in members(school=school, keyword=keyword)
    ]


def _tool_campus_dining(args: dict) -> Any:
    """餐饮点（食堂 / 咖啡轻食）。"""
    from westlake_survival.campus import dining

    campus = _opt_str(args, "campus")
    return _to_plain(dining(campus=campus))


def _tool_campus_housing(args: dict) -> Any:
    """校内公寓信息。"""
    from westlake_survival.campus import housing

    campus = _opt_str(args, "campus")
    return _to_plain(housing(campus=campus))


def _tool_affairs_apps(args: dict) -> Any:
    """办事大厅应用目录（免登录，176 个流程应用）。"""
    from westlake_survival.discovery import app_directory

    keyword = _opt_str(args, "keyword")
    limit = _opt_int(args, "limit", 30, minimum=1, maximum=200)
    items = app_directory(keyword)
    return {
        "count": len(items),
        "apps": [
            {"name": a.name, "department": a.department, "description": a.description}
            for a in items[:limit]
        ],
    }


def _tool_affairs_portal(args: dict) -> Any:
    """门户服务目录（18 项，含各部门站点；需统一密码）。"""
    from westlake_survival.discovery import portal_services

    rows = portal_services()
    return {"count": len(rows), "services": rows}


def _tool_career_latest(args: dict) -> Any:
    """就业服务网首页三区块（招聘公告/招聘会/宣讲会，免登录公开面）。"""
    from westlake_survival.careersite import announcements

    kind = _opt_str(args, "kind")
    keyword = _opt_str(args, "keyword")
    limit = _opt_int(args, "limit", 20, minimum=1, maximum=100)
    items = announcements(kind, keyword)
    return {
        "count": len(items),
        "site": "career.westlake.edu.cn",
        "note": "列表页与全部岗位检索需统一认证登录，未接入；条目 URL 直通官网详情",
        "items": [i.to_dict() for i in items[:limit]],
    }


def _tool_find_capability(args: dict) -> Any:
    """运行时自发现：按需求关键词搜 CLI/MCP/网页/学术库/服务注册表。"""
    from westlake_survival.capabilities import find_capabilities

    query = _opt_str(args, "query")
    if not query:
        raise ValueError("参数 query 不能为空（如：作业 / 论文 / 班车 / 待办）")
    result = find_capabilities(query)
    return {k: (v[:20] if isinstance(v, list) else v) for k, v in result.items()}


def _tool_scholar_databases(args: dict) -> Any:
    """学术数据库注册表（访问通道标注）。"""
    from westlake_survival.scholar import databases

    keyword = _opt_str(args, "keyword")
    rows = databases(keyword)
    return {
        "count": len(rows),
        "access_legend": "campus=校园IP carsi=CARSI联盟SSO open=免费 account=独立账号",
        "databases": [
            {
                "key": db.key,
                "name": db.name,
                "url": db.url,
                "category": db.category,
                "access": db.access,
                "vendor": db.vendor,
                "note": db.note,
            }
            for db in rows
        ],
    }


def _tool_scholar_resolve_doi(args: dict) -> Any:
    """DOI 解析：题录 + OA 副本 + 出版社 PDF 线索 + 校园网提示。"""
    from westlake_survival.scholar import resolve_doi

    doi = _opt_str(args, "doi")
    if not doi:
        raise ValueError("参数 doi 不能为空")
    paper = resolve_doi(doi, with_pdf_url=not args.get("pdf_url_only"))
    return paper.to_dict()


def _tool_scholar_campus(args: dict) -> Any:
    """校园网 IP 认证状态（出版社信标探测）。"""
    from westlake_survival.scholar import campus_status

    return campus_status(refresh=bool(args.get("refresh"))).to_dict()


def _tool_campus_map(args: dict) -> Any:
    """校园地图辅助：地址、地图图片、720yun 全景与到校交通。"""
    from westlake_survival.campusmap import campus_map

    campus = _opt_str(args, "campus")
    items = campus_map(campus)
    return [
        {
            "campus": item.name,
            "address": item.address,
            "postcode": item.postcode,
            "map_url": item.map_url,
            "panoramas": [
                {"title": p.title, "url": p.url, "img_url": p.img_url}
                for p in item.panoramas
            ],
            "traffic": item.traffic,
        }
        for item in items
    ]


def _tool_contact_info(args: dict) -> Any:
    """三校区地址交通 + 常用联系电话/邮箱。"""
    from westlake_survival.contact import GENERAL_CONTACTS, campuses, contacts

    return {
        "campuses": _to_plain(campuses()),
        "contacts": _to_plain(contacts()),
        "general": _to_plain(GENERAL_CONTACTS),
    }


def _tool_context_snapshot(args: dict) -> Any:
    """"此刻西湖"快照（日期 / 周次 / 事件 / 班车 / 天气）。"""
    from westlake_survival.context import Level, snapshot

    level_name = _opt_str(args, "level") or Level.NORMAL.value
    try:
        level = Level(level_name)
    except ValueError as exc:
        allowed = " / ".join(item.value for item in Level)
        raise ValueError(f"参数 level 必须是 {allowed} 之一，得到 {level_name!r}") from exc
    return _to_plain(snapshot(level).to_dict())


def _tool_canvas_todo(args: dict) -> Any:
    """Canvas 待办（users/self/todo）：课程 / 类型 / 事项 / 截止 / 链接。

    ``due_at`` 为北京时间（``+08:00``）的 ISO8601 字符串，不是 UTC。
    """
    from westlake_survival.canvas import canvas

    limit = _opt_int(args, "limit", 20, minimum=1, maximum=100)
    return canvas().todo(limit=limit)


def _tool_canvas_files(args: dict) -> Any:
    """某门课的文件区清单：``file_id`` / 文件名 / 字节大小。"""
    from westlake_survival.canvas import canvas

    course = _opt_keyword(args, "course")
    if not course:
        raise ValueError("参数 course 必填（课程 id 或名称关键词）。")
    client = canvas()
    found = client.find_course(course)
    return [
        {"file_id": item.id, "name": item.display_name, "size": item.size}
        for item in client.list_files(found.id)
    ]


def _tool_canvas_assignment_info(args: dict) -> Any:
    """作业详情：描述纯文本 + 描述内附件 + 截止/提交类型。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import html_to_text

    course = _opt_keyword(args, "course")
    assignment = _opt_keyword(args, "assignment")
    if not course or not assignment:
        raise ValueError("参数 course 与 assignment 必填（id 或名称关键词）。")
    client = canvas()
    found_course = client.find_course(course)
    found_assignment = client.find_assignment(found_course.id, assignment)
    detail = client.get_assignment(found_course.id, found_assignment.id)
    return {
        "course": found_course.name,
        "assignment_id": detail.id,
        "name": detail.name,
        "due_at": detail.due_at.isoformat() if detail.due_at else None,
        "points_possible": detail.points_possible,
        "submission_types": detail.submission_types,
        "locked_for_user": detail.locked_for_user,
        "allowed_extensions": detail.allowed_extensions,
        "allowed_attempts": detail.allowed_attempts,
        "grading_type": detail.grading_type,
        "rubric": detail.rubric,
        "rubric_settings": detail.rubric_settings,
        "description": html_to_text(detail.description or ""),
        "attachments": client.assignment_attachments(found_course.id, detail.id),
    }


def _tool_canvas_discussions(args: dict) -> Any:
    """课程讨论主题（标题 / 未读 / 回复数 / 北京时间 / 链接）。"""
    from westlake_survival.canvas import canvas

    course = _opt_keyword(args, "course")
    if not course:
        raise ValueError("参数 course 必填（课程 id 或名称关键词）。")
    client = canvas()
    found = client.find_course(course)
    return client.discussions(found.id)


def _tool_canvas_announcements(args: dict) -> Any:
    """课程公告（时间 / 标题 / 链接）。"""
    from westlake_survival.canvas import canvas

    course = _opt_keyword(args, "course")
    if not course:
        raise ValueError("参数 course 必填（课程 id 或名称关键词）。")
    client = canvas()
    found = client.find_course(course)
    return client.list_announcements(found.id)


def _tool_canvas_inbox(args: dict) -> Any:
    """收件箱会话列表 + 未读数。"""
    from westlake_survival.canvas import canvas

    limit = _opt_int(args, "limit", 20, minimum=1, maximum=100)
    client = canvas()
    return {"unread": client.unread_count(), "conversations": client.conversations(limit=limit)}


def _tool_canvas_conversation(args: dict) -> Any:
    """单个会话的完整消息与附件。"""
    from westlake_survival.canvas import canvas

    conversation_id = args.get("conversation_id")
    if isinstance(conversation_id, bool) or not isinstance(conversation_id, (int, str)):
        raise ValueError("参数 conversation_id 必填（整数，见 canvas_inbox 返回的 id）。")
    if not str(conversation_id).strip():
        raise ValueError("参数 conversation_id 不能为空。")
    return canvas().conversation(conversation_id)


def _tool_canvas_discussion_entries(args: dict) -> Any:
    """讨论主题详情 + 回帖（正文转纯文本）。"""
    from westlake_survival.canvas import canvas
    from westlake_survival.canvas.models import html_to_text

    course = _opt_keyword(args, "course")
    topic = _opt_keyword(args, "topic")
    if not course or not topic:
        raise ValueError("参数 course 与 topic 必填（课程/主题的 id 或名称关键词）。")
    limit = _opt_int(args, "limit", 20, minimum=1, maximum=200)
    client = canvas()
    found = client.find_course(course)
    topic_id = client.find_topic(found.id, topic)
    detail = client.discussion_topic(found.id, topic_id)
    entries = client.discussion_entries(found.id, topic_id, limit=limit)
    return {
        "topic": {
            "id": detail["id"],
            "title": detail["title"],
            "author": detail["author"],
            "posted_at": detail["posted_at"],
            "entries": detail["entries"],
            "url": detail["url"],
            "message": html_to_text(detail["message"]),
        },
        "entries": [
            {**item, "message": html_to_text(item["message"])} for item in entries
        ],
    }


def _tool_canvas_deadlines(args: dict) -> Any:
    """未来 N 天内到期的 Canvas 作业（令牌或统一密码会话均可）。"""
    from westlake_survival.canvas import CHINA_TZ, canvas

    days = _opt_int(args, "days", 14, minimum=1, maximum=180)
    now = datetime.now(CHINA_TZ)
    cutoff = now + timedelta(days=days)
    items = canvas().upcoming_deadlines(limit=200)
    selected = [
        item
        for item in items
        if item.due_at is not None and now <= item.due_at <= cutoff
    ]
    return [
        {
            "name": item.name,
            "due_at": item.due_at.isoformat(),
            "course_id": item.course_id,
            "url": item.html_url,
        }
        for item in selected
    ]


def _tool_canvas_submit(args: dict) -> Any:
    """提交 Canvas 作业（写操作）；``confirm=true`` 才真正提交，否则只预检。"""
    from westlake_survival.canvas import canvas, resolve_token

    if resolve_token() is None:
        raise ToolHint(
            "未配置 Canvas API token，无法提交作业。请在 Canvas 网页"
            "「账户 → 设置 → 新建访问令牌」生成令牌后，设置环境变量 "
            "WESTLAKE_CANVAS_TOKEN（或写入 ~/.westlake_survival/canvas_token.txt "
            "首行），再重试。"
        )

    course = _opt_keyword(args, "course")
    assignment = _opt_keyword(args, "assignment")
    if not course or not assignment:
        raise ValueError("参数 course 与 assignment 必填（课程/作业的 id 或名称关键词）。")
    raw_files = args.get("files") or []
    if not isinstance(raw_files, list) or not all(isinstance(i, str) and i for i in raw_files):
        raise ValueError("参数 files 须为本地文件路径的字符串数组。")
    text = _opt_str(args, "text")
    url = _opt_str(args, "url")
    confirm = bool(args.get("confirm"))

    client = canvas()
    found_course = client.find_course(course)
    found_assignment = client.find_assignment(found_course.id, assignment)
    plan = client.submit_assignment(
        found_course.id,
        found_assignment.id,
        file_paths=raw_files,
        text=text,
        url=url,
        dry_run=True,
    )
    plan.update(
        {
            "course_id": found_course.id,
            "course": f"{found_course.course_code or ''} {found_course.name}".strip(),
            "confirm": confirm,
        }
    )
    if not confirm:
        plan["hint"] = "预检通过但未提交。确认无误后带 confirm=true 重新调用才会真正提交。"
        return _to_plain(plan)
    submission = client.submit_assignment(
        found_course.id,
        found_assignment.id,
        file_paths=raw_files,
        text=text,
        url=url,
    )
    return _to_plain(
        {
            "submitted": True,
            "workflow_state": submission.workflow_state,
            "submitted_at": (
                submission.submitted_at.isoformat() if submission.submitted_at else None
            ),
            "late": submission.late,
            "attachments": [
                {"file_id": a.id, "name": a.display_name} for a in submission.attachments
            ],
            "preview_url": submission.preview_url,
        }
    )


# --------------------------------------------------------------------------- #
# 工具清单（name / description / inputSchema / handler）
# --------------------------------------------------------------------------- #
_CAMPUS_SCHEMA = {
    "type": "string",
    "enum": list(_CAMPUS_ENUM),
    "description": "校区名，缺省表示全部校区。",
}


def _schema(properties: dict[str, Any] | None = None,
            required: list[str] | None = None) -> dict[str, Any]:
    """构造一个 ``type: object`` 的 inputSchema（无参数时 ``properties`` 为空）。"""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _int_param(description: str, *, minimum: int, maximum: int | None = None) -> dict[str, Any]:
    """构造一个整数参数 schema。"""
    param: dict[str, Any] = {"type": "integer", "minimum": minimum, "description": description}
    if maximum is not None:
        param["maximum"] = maximum
    return param


def _str_param(description: str, *, enum: list[str] | None = None) -> dict[str, Any]:
    """构造一个字符串参数 schema。"""
    param: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        param["enum"] = enum
    return param

_TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "sis_schedule",
        "description": "取本学期 SIS 课表节次（课程 / 教师 / 星期 / 时间 / 地点）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_schedule,
    },
    {
        "name": "sis_grades",
        "description": "取全部学期成绩（学期 / 课程 / 等级 / 学分）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_grades,
    },
    {
        "name": "sis_exams",
        "description": "取当前学期考试安排（日期 / 时间 / 类型 / 考场 / 座位）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_exams,
    },
    {
        "name": "sis_evals_pending",
        "description": "取尚未完成的评教任务。",
        "inputSchema": _schema(),
        "handler": _tool_sis_evals_pending,
    },
    {
        "name": "sis_volunteer_history",
        "description": "取志愿服务历史（官方录入 + 自主提交，含总时长）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_volunteer_history,
    },
    {
        "name": "sis_registration",
        "description": "取学期注册缴费状态（个人信息 + 缴费开放提示）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_registration,
    },
    {
        "name": "sis_appointments",
        "description": "取本周心理预约（周范围 + 已占用时段）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_appointments,
    },
    {
        "name": "sis_clubs",
        "description": "取我的社团列表（学年 / 社团 / 发起人 / 人数）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_clubs,
    },
    {
        "name": "sis_second_class",
        "description": "取第二课堂成绩单（5 个维度 + 每项要求进度 + 未完成条数）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_second_class,
    },
    {
        "name": "sis_advisor",
        "description": "取学业导师：分配结果 + 各轮名单（配额 / 余量 / 志愿人数）。",
        "inputSchema": _schema(),
        "handler": _tool_sis_advisor,
    },
    {
        "name": "sis_other_applications",
        "description": "取学籍异动流程 / 困难认定 / 本博衔接 / 就业四类申请状态。",
        "inputSchema": _schema(),
        "handler": _tool_sis_other_applications,
    },
    {
        "name": "sites_index",
        "description": "取全部已接入站点索引（key / 名称 / 分组 / URL）。",
        "inputSchema": _schema(),
        "handler": _tool_sites_index,
    },
    {
        "name": "hosts_inventory",
        "description": "取全量子域清单（存活/不可达 / 标题 / 是否人工配置）。",
        "inputSchema": _schema(),
        "handler": _tool_hosts_inventory,
    },
    {
        "name": "hosts_content",
        "description": "取某个子域的栏目与条目（通用挖掘）。",
        "inputSchema": _schema({"host": _str_param("子域短名，如 career / its / officialweb-test。")}),
        "handler": _tool_hosts_content,
    },
    {
        "name": "site_content",
        "description": "取一个站点的栏目与条目（通知公告 / 新闻 / 答辩公告等）。",
        "inputSchema": _schema(
            {"key": {"type": "string", "description": "站点 key（见 sites_index）"}},
            required=["key"],
        ),
        "handler": _tool_site_content,
    },
    {
        "name": "site_detail",
        "description": "点进一条站内页面取详情：标题 / 正文摘要 / 附件下载（仅 *.westlake.edu.cn）。",
        "inputSchema": _schema(
            {"url": {"type": "string", "description": "条目页绝对 URL（来自 site_content）"}},
            required=["url"],
        ),
        "handler": _tool_site_detail,
    },
    {
        "name": "vpn_status",
        "description": "SSL VPN 会话状态与内网资源列表（需在网页 /vpn 手动登录过）。",
        "inputSchema": _schema(),
        "handler": _tool_vpn_status,
    },
    {
        "name": "hpc_ai",
        "description": "Westlake AI 大模型网关（OpenAI 兼容）：网关地址 / 领令牌入口 / 模型清单 / 存活探测。",
        "inputSchema": _schema(),
        "handler": _tool_hpc_ai,
    },
    {
        "name": "sis_statuses",
        "description": "取离校检查 / 生源确认 / 工时申报状态提示。",
        "inputSchema": _schema(),
        "handler": _tool_sis_statuses,
    },
    {
        "name": "calendar_today",
        "description": "今天的日期 / 星期 / 学期 / 教学周次 / 当日校历事件。",
        "inputSchema": _schema(),
        "handler": _tool_calendar_today,
    },
    {
        "name": "calendar_week",
        "description": "第 N 个教学周的起止日期（缺省取当前周）。",
        "inputSchema": _schema({"week": _int_param("教学周次，从 1 起。", minimum=1)}),
        "handler": _tool_calendar_week,
    },
    {
        "name": "transit_next",
        "description": "校园巴士下一批发车时刻（可指定始发校区）。",
        "inputSchema": _schema(
            {
                "campus": _CAMPUS_SCHEMA,
                "limit": _int_param("返回条数，默认 3。", minimum=1, maximum=20),
            }
        ),
        "handler": _tool_transit_next,
    },
    {
        "name": "news_latest",
        "description": "西湖新闻最新条目。",
        "inputSchema": _schema(
            {"limit": _int_param("最多返回条数，默认 10。", minimum=1, maximum=50)}
        ),
        "handler": _tool_news_latest,
    },
    {
        "name": "program_overview",
        "description": "本科培养理念：培养目标与八项培养特色（招生网公开数据，lang=zh/en）。",
        "inputSchema": _schema({"lang": _str_param("站点语言，默认 zh。", enum=["zh", "en"])}),
        "handler": _tool_program_overview,
    },
    {
        "name": "program_curriculum",
        "description": "本科课程体系：核心课程、通识课程简表、专业课程与专业选定规则（招生网公开数据）。",
        "inputSchema": _schema({"lang": _str_param("站点语言，默认 zh。", enum=["zh", "en"])}),
        "handler": _tool_program_curriculum,
    },
    {
        "name": "program_majors",
        "description": "本科专业设置：8 个专业（理学/工学/医学）总览与分专业介绍（招生网公开数据）。",
        "inputSchema": _schema({"lang": _str_param("站点语言，默认 zh。", enum=["zh", "en"])}),
        "handler": _tool_program_majors,
    },
    {
        "name": "program_courses",
        "description": "通识课程目录：理工基础/人文社科艺术/基础素质三类，含学分、开课学期、先修与授课教师。",
        "inputSchema": _schema(
            {
                "category": _str_param("类别片段，如「理工」「人文」「素质」。"),
                "keyword": _str_param("课程名/学科/简介关键词。"),
                "detail": {"type": "boolean", "description": "是否包含课程简介。"},
            }
        ),
        "handler": _tool_program_courses,
    },
    {
        "name": "program_course_search",
        "description": "跨源课程搜索：查某门课在通识目录与各专业培养方案里的归属、学分与先修。",
        "inputSchema": _schema(
            {
                "keyword": _str_param("课程名子串，如「机器学习」。"),
                "common_only": {"type": "boolean", "description": "只搜通识目录。"},
                "detail": {"type": "boolean", "description": "是否包含课程简介。"},
            },
            required=["keyword"],
        ),
        "handler": _tool_program_course_search,
    },
    {
        "name": "program_plan",
        "description": "专业培养方案：按学分块列出的学分要求与课程表，含先修课程（主站公开页，中文）。",
        "inputSchema": _schema(
            {
                "major": _str_param("专业中文名或子串，如「人工智能」；缺省返回全部 8 个专业。"),
                "detail": {"type": "boolean", "description": "是否包含每门课的课程简介。"},
            }
        ),
        "handler": _tool_program_plan,
    },
    {
        "name": "events_upcoming",
        "description": "未来 N 天内的活动预告（含今天）。",
        "inputSchema": _schema(
            {"days": _int_param("未来天数窗口，默认 14。", minimum=0, maximum=90)}
        ),
        "handler": _tool_events_upcoming,
    },
    {
        "name": "research_latest",
        "description": "科研进展最新条目。",
        "inputSchema": _schema(
            {"limit": _int_param("最多返回条数，默认 10。", minimum=1, maximum=50)}
        ),
        "handler": _tool_research_latest,
    },
    {
        "name": "site_search",
        "description": "西湖大学官网全站搜索。",
        "inputSchema": _schema(
            {
                "query": _str_param("检索词。"),
                "page": _int_param("页码，从 1 起，默认 1。", minimum=1),
            },
            required=["query"],
        ),
        "handler": _tool_site_search,
    },
    {
        "name": "faculty_search",
        "description": "教师名录检索（可按学院或关键词过滤）。",
        "inputSchema": _schema(
            {
                "school": _str_param("学院名，如「理学院」「工学院」。"),
                "keyword": _str_param("关键词，匹配姓名 / 英文名 / 学科 / 实验室。"),
            }
        ),
        "handler": _tool_faculty_search,
    },
    {
        "name": "campus_dining",
        "description": "餐饮点信息（食堂 / 咖啡轻食 的位置、供餐与营业时间）。",
        "inputSchema": _schema({"campus": _CAMPUS_SCHEMA}),
        "handler": _tool_campus_dining,
    },
    {
        "name": "campus_housing",
        "description": "校内公寓信息（地址、配套服务、联系电话）。",
        "inputSchema": _schema({"campus": _CAMPUS_SCHEMA}),
        "handler": _tool_campus_housing,
    },
    {
        "name": "affairs_apps",
        "description": "网上办事大厅应用目录（免登录）：176 个流程应用，可按名称/部门过滤。",
        "inputSchema": _schema(
            {
                "keyword": _str_param("应用名或部门子串，如「预约」「出入」「信息技术中心」。"),
                "limit": _int_param("最多返回条数，默认 30。", minimum=1, maximum=200),
            }
        ),
        "handler": _tool_affairs_apps,
    },
    {
        "name": "affairs_portal",
        "description": "门户服务目录（18 项部门/应用站点，需统一密码）。",
        "inputSchema": _schema(),
        "handler": _tool_affairs_portal,
    },
    {
        "name": "campus_map",
        "description": "校园地图辅助：三校区地址、官方地图图片、720yun 校园全景与到校交通（含地铁公交首末班）。",
        "inputSchema": _schema(
            {"campus": _str_param("校区片段：云谷 / 云栖 / 铜鉴湖；缺省返回全部。")}
        ),
        "handler": _tool_campus_map,
    },
    {
        "name": "contact_info",
        "description": "三校区地址与交通 + 常用联系电话 / 邮箱。",
        "inputSchema": _schema(),
        "handler": _tool_contact_info,
    },
    {
        "name": "context_snapshot",
        "description": "「此刻西湖」快照：日期 / 周次 / 校历事件 / 班车 / 天气 / 待办截止。",
        "inputSchema": _schema(
            {"level": _str_param("信息量档位，默认 normal。", enum=["terse", "normal", "verbose"])}
        ),
        "handler": _tool_context_snapshot,
    },
    {
        "name": "canvas_deadlines",
        "description": "未来 N 天内到期的 Canvas 作业截止（令牌或统一密码会话均可）。",
        "inputSchema": _schema(
            {"days": _int_param("未来天数窗口，默认 14。", minimum=1, maximum=180)}
        ),
        "handler": _tool_canvas_deadlines,
    },
    {
        "name": "canvas_todo",
        "description": "Canvas 待办列表（课程 / 类型 / 事项 / 截止 / 链接）；截止为北京时间 ISO8601。",
        "inputSchema": _schema(
            {"limit": _int_param("返回条数，默认 20。", minimum=1, maximum=100)}
        ),
        "handler": _tool_canvas_todo,
    },
    {
        "name": "canvas_files",
        "description": "某门 Canvas 课程的文件区清单（file_id / 文件名 / 字节大小）。",
        "inputSchema": _schema(
            {"course": _str_param("课程 id 或名称关键词。")},
            ["course"],
        ),
        "handler": _tool_canvas_files,
    },
    {
        "name": "canvas_assignment_info",
        "description": (
            "作业详情：描述纯文本、描述内附件（file_id/名称/大小）、"
            "截止时间（北京时间 ISO8601）与提交类型。"
        ),
        "inputSchema": _schema(
            {
                "course": _str_param("课程 id 或名称关键词。"),
                "assignment": _str_param("作业 id 或名称关键词。"),
            },
            ["course", "assignment"],
        ),
        "handler": _tool_canvas_assignment_info,
    },
    {
        "name": "canvas_discussions",
        "description": "课程讨论主题（标题 / 未读 / 回复数 / 北京时间 / 链接）。",
        "inputSchema": _schema(
            {"course": _str_param("课程 id 或名称关键词。")},
            ["course"],
        ),
        "handler": _tool_canvas_discussions,
    },
    {
        "name": "canvas_announcements",
        "description": "课程公告（时间 / 标题 / 链接）。",
        "inputSchema": _schema(
            {"course": _str_param("课程 id 或名称关键词。")},
            ["course"],
        ),
        "handler": _tool_canvas_announcements,
    },
    {
        "name": "canvas_inbox",
        "description": "收件箱会话列表（未读数 + 主题 / 参与者 / 最近消息时间）。",
        "inputSchema": _schema(
            {"limit": _int_param("返回条数，默认 20。", minimum=1, maximum=100)}
        ),
        "handler": _tool_canvas_inbox,
    },
    {
        "name": "canvas_conversation",
        "description": "单个会话的完整消息与附件（conversation_id 取自 canvas_inbox）。",
        "inputSchema": _schema(
            {
                "conversation_id": {
                    "type": "integer",
                    "description": "会话 id（canvas_inbox 返回的 conversation id）。",
                }
            },
            ["conversation_id"],
        ),
        "handler": _tool_canvas_conversation,
    },
    {
        "name": "canvas_discussion_entries",
        "description": "讨论主题详情 + 回帖列表（正文已转纯文本）。",
        "inputSchema": _schema(
            {
                "course": _str_param("课程 id 或名称关键词。"),
                "topic": _str_param("讨论主题 id 或标题关键词。"),
                "limit": _int_param("回帖条数，默认 20。", minimum=1, maximum=200),
            },
            ["course", "topic"],
        ),
        "handler": _tool_canvas_discussion_entries,
    },
    {
        "name": "canvas_submit",
        "description": (
            "提交 Canvas 作业（写操作，需 Canvas API token）：上传文件 / 文本 / 链接。"
            "缺省只预检返回提交计划；confirm=true 才真正提交。"
        ),
        "inputSchema": _schema(
            {
                "course": _str_param("课程 id 或名称关键词。"),
                "assignment": _str_param("作业 id 或名称关键词。"),
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "本地文件路径列表（online_upload 提交方式）。",
                },
                "text": _str_param("文本提交内容（online_text_entry）。"),
                "url": _str_param("链接提交地址（online_url）。"),
                "confirm": {
                    "type": "boolean",
                    "description": "true 时真正提交；缺省只预检。文件/文本/链接三选一。",
                },
            },
            ["course", "assignment"],
        ),
        "handler": _tool_canvas_submit,
    },
    {
        "name": "career_latest",
        "description": (
            "就业服务网最新动态：招聘公告 / 招聘会 / 宣讲会三区块"
            "（首页公开面，含日期、时段、场地与状态）。"
        ),
        "inputSchema": _schema(
            {
                "kind": _str_param(
                    "类型过滤：campus=招聘公告 jobfair=招聘会 teachin=宣讲会；缺省全部。",
                    enum=["campus", "jobfair", "teachin"],
                ),
                "keyword": _str_param("标题/场地子串过滤。"),
                "limit": _int_param("最多返回条数，默认 20。", minimum=1, maximum=100),
            }
        ),
        "handler": _tool_career_latest,
    },
    {
        "name": "find_capability",
        "description": (
            "需求→能力路由：不确定某需求归哪条命令/工具时先搜这个"
            "（支持口语同义词，如「论文」匹配学术资源、「借书」匹配图书馆）。"
        ),
        "inputSchema": _schema(
            {"query": _str_param("需求关键词，如：作业 / 论文 / 班车 / 待办 / 预约。")},
            ["query"],
        ),
        "handler": _tool_find_capability,
    },
    {
        "name": "scholar_databases",
        "description": (
            "学术数据库注册表：中西文全文/引文索引/事实库/数据平台，"
            "标注访问通道（campus=校园IP carsi=CARSI联盟SSO open=免费 account=独立账号）。"
        ),
        "inputSchema": _schema(
            {"keyword": _str_param("名称/类别/厂商子串，如「知网」「外文全文」。缺省全部。")}
        ),
        "handler": _tool_scholar_databases,
    },
    {
        "name": "scholar_resolve_doi",
        "description": (
            "解析 DOI：CrossRef 题录 + OA 副本 + 出版社 citation_pdf_url，"
            "并提示当前出口 IP 是否在校园网认证范围（订阅全文可直接取）。"
        ),
        "inputSchema": _schema(
            {
                "doi": _str_param("DOI，接受裸 DOI 或 doi.org 链接。"),
                "pdf_url_only": {
                    "type": "boolean",
                    "description": "true 时跳过出版社落地页探测（更快），只给题录与 OA。",
                },
            },
            ["doi"],
        ),
        "handler": _tool_scholar_resolve_doi,
    },
    {
        "name": "scholar_campus",
        "description": "当前出口 IP 是否被出版社认作校园网（信标探测，缓存 30 分钟）。",
        "inputSchema": _schema(
            {"refresh": {"type": "boolean", "description": "true 时强制重新探测。"}}
        ),
        "handler": _tool_scholar_campus,
    },
)

#: 工具名 → spec，供分发用（保持定义顺序）。
_TOOLS_BY_NAME: dict[str, dict[str, Any]] = {spec["name"]: spec for spec in _TOOL_SPECS}


def list_tools() -> list[dict[str, Any]]:
    """``tools/list`` 的载荷（不含内部 handler）。"""
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
        }
        for spec in _TOOL_SPECS
    ]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行一个工具，返回 MCP 的 ``tools/call`` 结果对象。

    工具内部异常一律转成 ``isError: true`` 的可读文本，绝不向上抛；只有工具名
    不存在时才由调用方（:func:`dispatch`）转成 JSON-RPC ``-32602``。
    """
    spec = _TOOLS_BY_NAME.get(name)
    if spec is None:
        raise KeyError(name)
    args = arguments if isinstance(arguments, dict) else {}
    try:
        payload = spec["handler"](args)
    except ToolHint as hint:
        return {"content": [{"type": "text", "text": str(hint)}]}
    except Exception as exc:  # noqa: BLE001 - 工具边界：任何异常都转 isError
        logger.warning("工具 %s 执行失败：%s: %s", name, type(exc).__name__, exc)
        message = str(exc) or type(exc).__name__
        return {
            "content": [{"type": "text", "text": f"{type(exc).__name__}: {message}"}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": _dumps(payload)}]}


# --------------------------------------------------------------------------- #
# JSON-RPC 分发
# --------------------------------------------------------------------------- #
def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    version = params.get("protocolVersion")
    if not isinstance(version, str) or not version.strip():
        version = DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": version.strip(),
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
        "capabilities": {"tools": {"listChanged": False}},
    }


def dispatch(message: Any) -> dict[str, Any] | None:
    """处理一条已解析的 JSON-RPC 消息；通知（无 ``id``）返回 ``None``。"""
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, "请求必须是 JSON 对象")

    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _error(request_id, INVALID_REQUEST, "缺少 method 字段")

    is_notification = "id" not in message or request_id is None
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    try:
        if method == "initialize":
            result = _initialize(params)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": list_tools()}
        elif method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return None if is_notification else _error(
                    request_id, INVALID_PARAMS, "tools/call 缺少 name 参数"
                )
            try:
                result = call_tool(name, params.get("arguments"))
            except KeyError:
                return None if is_notification else _error(
                    request_id, INVALID_PARAMS, f"未知工具：{name}"
                )
        elif method.startswith("notifications/"):
            # initialized / cancelled / progress 等通知：静默忽略。
            return None
        else:
            return None if is_notification else _error(
                request_id, METHOD_NOT_FOUND, f"未知方法：{method}"
            )
    except Exception as exc:  # noqa: BLE001 - 分发边界：兜底为内部错误
        logger.exception("处理方法 %s 时发生未预期异常", method)
        return None if is_notification else _error(
            request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"
        )

    if is_notification:
        return None
    return _result(request_id, result)


def handle_line(line: str) -> str | None:
    """处理一行输入文本，返回一行待写出的响应；通知/空行返回 ``None``。"""
    text = line.strip()
    if not text:
        return None
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("无法解析输入行：%s", exc)
        return _dumps(_error(None, PARSE_ERROR, f"JSON 解析失败：{exc.msg}"))
    if isinstance(message, list):
        return _dumps(_error(None, INVALID_REQUEST, "不支持 JSON-RPC 批量请求"))
    response = dispatch(message)
    return _dumps(response) if response is not None else None


def serve(stdin: Iterable[str] | None = None, stdout: Any = None) -> None:
    """逐行读取 ``stdin``、写响应到 ``stdout``；读到 EOF 即返回。"""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    for raw in source:
        response = handle_line(raw)
        if response is None:
            continue
        sink.write(response + "\n")
        sink.flush()


def _force_utf8(stream: Any) -> None:
    """尽量把标准流重配为 UTF-8（Windows 管道默认可能是 GBK，中文会编不出去）。"""
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8")
    except (ValueError, OSError):  # pragma: no cover - 流不可重配（已替换等）
        pass


def main() -> int:
    """入口：``python -m westlake_survival.mcp_server``。"""
    logging.basicConfig(
        stream=sys.stderr,
        level=os.environ.get("WESTLAKE_MCP_LOG", "WARNING").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _force_utf8(sys.stdin)
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    logger.info("%s MCP server 启动（stdio）", SERVER_NAME)
    serve()
    logger.info("%s MCP server 退出（stdin EOF）", SERVER_NAME)
    return 0


if __name__ == "__main__":  # pragma: no cover - 由 __main__ / 测试覆盖
    raise SystemExit(main())
