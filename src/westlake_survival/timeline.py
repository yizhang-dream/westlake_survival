"""今日时空行动流（Timeline）与多源日程冲突求解器。

面向西湖大学师生的日常行动决策中枢：
1. 跨系统融合：校历周次、当天课表（SIS/AMS）、Canvas 截止倒计时、
   场地预约、校车接驳建议与个人备忘事项，按时间轴（Timeline）排序；
2. 冲突求解器：自动计算全天日程重叠时间区间，标出冲突事件；
3. 离线优先：全部数据源走 SWR（Stale-While-Revalidate），脱机/断网/无 VPN 也能秒级渲染历史快照；
4. 个人备忘写操作：受控写操作门禁，支持快速添加和标记完成个人日程行动项。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as time_cls
from pathlib import Path
from typing import Any

from westlake_survival._cache import config_root, fetch_with_swr
from westlake_survival.canvas.models import format_remaining
from westlake_survival.exceptions import WestlakeError

logger = logging.getLogger(__name__)

__all__ = [
    "TimelineItem",
    "TimelineMemo",
    "TimelineReport",
    "add_memo",
    "build_timeline",
    "delete_memo",
    "detect_timeline_conflicts",
    "list_memos",
    "toggle_memo",
]


@dataclass
class TimelineItem:
    """时间轴上的一个日程事件。"""

    time_str: str  # 显示时间，如 "09:00-10:20" 或 "23:59"
    sort_time: str  # 排序用时间，如 "09:00"
    category: str  # "course", "canvas", "booking", "transit", "memo", "holiday"
    title: str
    location: str = ""
    status: str = ""
    details: str = ""
    is_conflict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineMemo:
    """个人生活备忘/行动项。"""

    id: str
    text: str
    time_str: str = ""
    done: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineReport:
    """全天时空编排完整报告。"""

    date_str: str
    term_info: str
    items: list[TimelineItem]
    conflicts: list[str]
    memos: list[TimelineMemo]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date_str,
            "term_info": self.term_info,
            "items": [it.to_dict() for it in self.items],
            "conflicts": self.conflicts,
            "memos": [m.to_dict() for m in self.memos],
            "meta": self.meta,
        }


def _memos_file() -> Path:
    p = config_root() / "timeline_memos.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def list_memos() -> list[TimelineMemo]:
    """读取所有未完成或今天的个人备忘。"""
    path = _memos_file()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [TimelineMemo(**item) for item in raw]
    except Exception:
        return []


def _save_memos(memos: list[TimelineMemo]) -> None:
    path = _memos_file()
    try:
        path.write_text(
            json.dumps([m.to_dict() for m in memos], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def add_memo(text: str, time_str: str = "") -> TimelineMemo:
    """添加一条个人生活备忘（写操作）。"""
    memo_id = "memo-" + uuid.uuid4().hex[:6]
    memo = TimelineMemo(id=memo_id, text=text.strip(), time_str=time_str.strip())
    memos = list_memos()
    memos.append(memo)
    _save_memos(memos)
    return memo


def toggle_memo(memo_id: str, done: bool = True) -> TimelineMemo:
    """标记个人生活备忘完成状态（写操作）。"""
    memos = list_memos()
    target = None
    for m in memos:
        if m.id == memo_id or m.id.endswith(memo_id):
            m.done = done
            target = m
            break
    if not target:
        raise WestlakeError(f"未找到备忘条目 [{memo_id}]")
    _save_memos(memos)
    return target


def delete_memo(memo_id: str) -> bool:
    """删除指定个人备忘。"""
    memos = list_memos()
    orig_len = len(memos)
    memos = [m for m in memos if m.id != memo_id and not m.id.endswith(memo_id)]
    if len(memos) < orig_len:
        _save_memos(memos)
        return True
    return False


def _parse_span_minutes(time_str: str) -> tuple[int, int] | None:
    """解析 'HH:MM-HH:MM' 或 'HH:MM' 为从 0 点起的分钟数范围。"""
    s = time_str.strip()
    if "-" in s:
        parts = s.split("-")
        try:
            h1, m1 = map(int, parts[0].split(":"))
            h2, m2 = map(int, parts[1].split(":"))
            return h1 * 60 + m1, h2 * 60 + m2
        except Exception:
            return None
    elif ":" in s:
        try:
            h, m = map(int, s.split(":"))
            start = h * 60 + m
            return start, start + 30
        except Exception:
            return None
    return None


def detect_timeline_conflicts(items: list[TimelineItem]) -> list[str]:
    """检测时间轴上的时间重叠冲突。"""
    conflicts: list[str] = []
    schedulable: list[tuple[int, int, TimelineItem]] = []
    for it in items:
        # 仅针对具有真实时间区间的课程、预约进行重叠判定
        if it.category in ("course", "booking"):
            span = _parse_span_minutes(it.time_str)
            if span and span[0] < span[1]:
                schedulable.append((span[0], span[1], it))

    n = len(schedulable)
    for i in range(n):
        for j in range(i + 1, n):
            s1, e1, it1 = schedulable[i]
            s2, e2, it2 = schedulable[j]
            # 同课同时段多教室（如分教室平行实验/大课）不是冲突
            if (
                it1.category == "course"
                and it2.category == "course"
                and it1.title == it2.title
                and s1 == s2
                and e1 == e2
            ):
                continue
            # 判断交集非空
            if max(s1, s2) < min(e1, e2):
                it1.is_conflict = True
                it2.is_conflict = True
                msg = f"时间冲突：[{it1.time_str}] {it1.title} 与 [{it2.time_str}] {it2.title} 存在重叠时段"
                if msg not in conflicts:
                    conflicts.append(msg)
    return conflicts


def _merge_locations(locations: list[str]) -> str:
    """合并平行教室地点列表并去重，同校区后续地点省略重复校区前缀。"""
    unique: list[str] = []
    for loc in locations:
        text = str(loc or "").strip()
        if text and text != "待定教室" and text not in unique:
            unique.append(text)
    if not unique:
        return "待定教室"
    if len(unique) == 1:
        return unique[0]
    for prefix in ("云谷校区", "云栖校区"):
        if unique[0].startswith(prefix):
            merged = [unique[0]]
            for item in unique[1:]:
                if item.startswith(prefix):
                    merged.append(item[len(prefix) :].lstrip())
                else:
                    merged.append(item)
            return " / ".join(x for x in merged if x)
    return " / ".join(unique)


def _merge_parallel_courses(raw_items: list[TimelineItem]) -> list[TimelineItem]:
    """合并同课同时段的平行教室条目，避免时间轴出现多张重复课程卡片。"""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    others: list[TimelineItem] = []
    for it in raw_items:
        if it.category != "course":
            others.append(it)
            continue
        key = (it.sort_time, it.time_str, it.title)
        bucket = grouped.get(key)
        if bucket is None:
            grouped[key] = {"item": it, "locs": [it.location] if it.location else []}
        elif it.location:
            bucket["locs"].append(it.location)

    merged_courses: list[TimelineItem] = []
    for bucket in grouped.values():
        it: TimelineItem = bucket["item"]
        merged_courses.append(
            TimelineItem(
                time_str=it.time_str,
                sort_time=it.sort_time,
                category=it.category,
                title=it.title,
                location=_merge_locations(bucket["locs"]),
                status=it.status,
                details=it.details,
                is_conflict=it.is_conflict,
            )
        )
    return merged_courses + others


def build_timeline(*, target_date: date | None = None, offline: bool = False) -> TimelineReport:
    """构建指定日期（默认今天）的全局时空编排报告。

    支持离线优先（SWR 降级）与三源并发拉取，无网环境下自动秒出。
    """
    now_date = target_date or date.today()
    date_str = now_date.strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now_date.weekday()]
    full_date_title = f"{date_str} {weekday_cn}"

    items: list[TimelineItem] = []
    is_stale = offline
    stale_reasons: list[str] = []

    # 1. 校历与学期周次（AcademicCalendar.load 自带 ETag 缓存与内置离线兜底）
    term_info = "非教学期"
    sem = None
    week_num: int | None = None
    china_tz = None
    try:
        from westlake_survival.calendar import AcademicCalendar, CHINA_TZ

        china_tz = CHINA_TZ
        cal = AcademicCalendar.load(offline=offline)
        sem = cal.semester_for(now_date)
        if sem:
            week_num = sem.week_of(now_date)
            term_info = f"{sem.name} 第 {week_num} 周" if week_num else sem.name
            covering_holidays = (
                [e for e in sem.holiday_events() if e.covers(now_date)]
                if sem.is_holiday(now_date)
                else []
            )
            emitted_titles: set[str] = set()
            for holiday in covering_holidays:
                emitted_titles.add(holiday.title)
                items.append(
                    TimelineItem(
                        time_str="全天",
                        sort_time="00:00",
                        category="holiday",
                        title=f"校历假期：{holiday.title}",
                        location="全校",
                        status="假期",
                    )
                )
            for ev in sem.events:
                if ev.title not in emitted_titles and ev.covers(now_date):
                    emitted_titles.add(ev.title)
                    items.append(
                        TimelineItem(
                            time_str="全天",
                            sort_time="00:01",
                            category="holiday",
                            title=f"校历提示：{ev.title}",
                            location="全校",
                            status="校历事件",
                        )
                    )
            if now_date in sem.makeup_days():
                items.append(
                    TimelineItem(
                        time_str="调休补课",
                        sort_time="00:02",
                        category="holiday",
                        title="校历提示：今日为调休补课日",
                        location="全校",
                        status="调休补课",
                    )
                )
    except Exception as exc:
        stale_reasons.append(f"校历: {exc}")
        term_info = "西湖大学校历（离线）"

    skip_courses = bool(sem and sem.is_holiday(now_date))

    def _load_courses() -> tuple[list[TimelineItem], bool, list[str]]:
        if skip_courses:
            return [], False, []
        local_items: list[TimelineItem] = []
        local_stale = False
        local_errs: list[str] = []
        sis_err: str | None = None
        sis_rows: list[dict[str, Any]] = []
        course_keys: set[tuple[str, str]] = set()

        def _fetch_sis_rows() -> list[dict[str, Any]]:
            from westlake_survival.sis import get_schedule

            return [
                {
                    "course_code": s.course_code,
                    "title": s.title,
                    "teacher": s.teacher,
                    "weekday": s.weekday,
                    "start": s.start_time.strftime("%H:%M"),
                    "end": s.end_time.strftime("%H:%M"),
                    "room": s.room,
                    "date_start": s.date_start.isoformat(),
                    "date_end": s.date_end.isoformat(),
                    "weeks": list(s.weeks) if s.weeks else None,
                }
                for s in get_schedule()
            ]

        try:
            sis_rows, meta = fetch_with_swr("sis", "schedule", _fetch_sis_rows, offline=offline)
            if meta.get("is_stale"):
                local_stale = True
            today_weekday = now_date.isoweekday()
            for row in sis_rows or []:
                if row.get("weekday") != today_weekday:
                    continue
                ds_str = row.get("date_start")
                de_str = row.get("date_end")
                if ds_str and de_str:
                    try:
                        ds = date.fromisoformat(str(ds_str))
                        de = date.fromisoformat(str(de_str))
                        if ds.year >= 2000 and de.year >= 2000 and not (ds <= now_date <= de):
                            continue
                    except ValueError:
                        pass
                weeks = row.get("weeks")
                if weeks and week_num is not None and week_num not in weeks:
                    continue
                start_t = str(row.get("start") or "").strip()
                end_t = str(row.get("end") or "").strip()
                time_range = (
                    f"{start_t}-{end_t}"
                    if start_t and end_t
                    else str(row.get("time") or "").strip()
                )
                sort_t = start_t or (
                    time_range.split("-")[0].strip() if "-" in time_range else "08:00"
                )
                title = str(row.get("title") or row.get("name") or "课程").strip()
                room = str(row.get("room") or row.get("location") or "待定教室").strip()
                code = str(row.get("course_code") or row.get("course") or "—").strip()
                teacher = str(row.get("teacher") or "").strip()
                details = f"课程代码: {code}" + (f" · {teacher}" if teacher else "")
                course_keys.add((sort_t, title))
                local_items.append(
                    TimelineItem(
                        time_str=time_range or "时间待定",
                        sort_time=sort_t,
                        category="course",
                        title=title,
                        location=room,
                        status="已选课程",
                        details=details,
                    )
                )
        except Exception as exc:
            sis_err = f"SIS: {exc}"

        if not sis_rows or sis_err is not None:
            try:
                from westlake_survival import ams

                ams_rows, ams_meta = fetch_with_swr(
                    "ams",
                    f"schedule_{date_str}",
                    lambda: ams.schedule(now_date, now_date),
                    offline=offline,
                )
                if ams_meta.get("is_stale"):
                    local_stale = True
                for row in ams_rows or []:
                    start_t = str(row.get("start") or "").strip()
                    end_t = str(row.get("end") or "").strip()
                    title = str(row.get("title") or "课程").strip()
                    if not title:
                        continue
                    sort_t = start_t or "08:00"
                    if (sort_t, title) in course_keys:
                        continue
                    course_keys.add((sort_t, title))
                    time_range = (
                        f"{start_t}-{end_t}"
                        if start_t and end_t
                        else (start_t or ("全天" if row.get("whole_day") else "时间待定"))
                    )
                    local_items.append(
                        TimelineItem(
                            time_str=time_range,
                            sort_time=sort_t,
                            category="course",
                            title=title,
                            location=str(row.get("address") or "待定教室"),
                            status="已选课程 (AMS)",
                            details="来源: 教学系统 AMS",
                        )
                    )
            except Exception as ams_exc:
                if sis_err is not None and not course_keys:
                    local_errs.append(f"课表: {sis_err}; AMS: {ams_exc}")

        return _merge_parallel_courses(local_items), local_stale, local_errs

    def _load_canvas() -> tuple[list[TimelineItem], bool, list[str]]:
        local_items: list[TimelineItem] = []
        local_stale = False
        local_errs: list[str] = []
        try:
            from westlake_survival.canvas import canvas

            def _fetch_deadlines():
                client = canvas()
                res = []
                for a in client.upcoming_deadlines(limit=25):
                    res.append({
                        "name": a.name,
                        "due_at": a.due_at.isoformat() if a.due_at else None,
                        "html_url": a.html_url,
                        "points_possible": a.points_possible,
                    })
                return res

            deadlines_raw, meta = fetch_with_swr(
                "canvas", "deadlines", _fetch_deadlines, offline=offline
            )
            if meta.get("is_stale"):
                local_stale = True

            for d in deadlines_raw or []:
                due_at_str = d.get("due_at")
                if due_at_str:
                    try:
                        dt = datetime.fromisoformat(due_at_str)
                        if dt.tzinfo is not None and china_tz is not None:
                            dt = dt.astimezone(china_tz)
                        if dt.date() == now_date:
                            local_items.append(
                                TimelineItem(
                                    time_str=dt.strftime("%H:%M"),
                                    sort_time=dt.strftime("%H:%M"),
                                    category="canvas",
                                    title=f"DDL 截止: {d.get('name')}",
                                    location="Canvas",
                                    status=f"待提交作业（{format_remaining(dt)}）",
                                    details=f"分值: {d.get('points_possible') or '—'} 分",
                                )
                            )
                    except Exception:
                        pass
        except Exception as exc:
            local_errs.append(f"Canvas: {exc}")
        return local_items, local_stale, local_errs

    def _load_bookings() -> tuple[list[TimelineItem], bool, list[str]]:
        local_items: list[TimelineItem] = []
        local_stale = False
        local_errs: list[str] = []
        try:
            from westlake_survival import booking

            def _fetch_bookings():
                return [b.to_dict() for b in booking.my_bookings()]

            b_rows, meta = fetch_with_swr("booking", "mine", _fetch_bookings, offline=offline)
            if meta.get("is_stale"):
                local_stale = True

            for b in b_rows or []:
                if b.get("date") == date_str and b.get("state") not in ("3", "取消"):
                    start_t = b.get("start", "")
                    end_t = b.get("end", "")
                    local_items.append(
                        TimelineItem(
                            time_str=f"{start_t}-{end_t}",
                            sort_time=start_t or "12:00",
                            category="booking",
                            title=f"场地使用: {b.get('resource')}",
                            location=str(b.get("resource") or "预约中心"),
                            status="已预约",
                            details=f"预约ID: {b.get('id')}",
                        )
                    )
        except Exception as exc:
            local_errs.append(f"预约: {exc}")
        return local_items, local_stale, local_errs

    # 2~4. 课表 / Canvas / 预约三源并发拉取
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_courses = pool.submit(_load_courses)
        f_canvas = pool.submit(_load_canvas)
        f_bookings = pool.submit(_load_bookings)
        for fut in (f_courses, f_canvas, f_bookings):
            part_items, part_stale, part_errs = fut.result()
            items.extend(part_items)
            if part_stale:
                is_stale = True
            stale_reasons.extend(part_errs)

    # 5. 班车接驳建议（当日存在课程或预约时生成）
    try:
        from westlake_survival.transit import transit

        has_day_activity = any(it.category in ("course", "booking") for it in items)
        if has_day_activity:
            t_data = transit(offline=offline)
            ref_dt = (
                datetime.now(china_tz)
                if now_date == date.today()
                else datetime.combine(now_date, time_cls(7, 20), tzinfo=china_tz)
            )
            for tbl, hhmm in t_data.next_departures(now=ref_dt, limit=2):
                items.append(
                    TimelineItem(
                        time_str=hhmm,
                        sort_time=hhmm,
                        category="transit",
                        title=f"接驳班车: {hhmm} 从 {tbl.campus.value} 开出",
                        location=tbl.campus.value,
                        status=tbl.day_kind.value,
                        details=tbl.direction_note or "预留从容抵达与进教室时间",
                    )
                )
    except Exception:
        pass

    # 6. 本地个人备忘
    memos = list_memos()
    for m in memos:
        if not m.done:
            items.append(
                TimelineItem(
                    time_str=m.time_str or "随时",
                    sort_time=m.time_str if m.time_str and ":" in m.time_str else "20:00",
                    category="memo",
                    title=f"个人待办: {m.text}",
                    location="个人记事",
                    status="待完成",
                    details=f"memo_id: {m.id}",
                )
            )

    # 7. 排序时间轴
    items.sort(key=lambda x: (x.sort_time, x.time_str))

    # 8. 冲突检测求解
    conflicts = detect_timeline_conflicts(items)

    meta_info = {
        "offline_requested": offline,
        "is_stale": is_stale,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fallback_reasons": stale_reasons,
    }

    return TimelineReport(
        date_str=full_date_title,
        term_info=term_info,
        items=items,
        conflicts=conflicts,
        memos=memos,
        meta=meta_info,
    )
