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
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from westlake_survival._cache import config_root, fetch_with_swr, load_snapshot, save_snapshot
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
            # 判断交集非空
            if max(s1, s2) < min(e1, e2):
                it1.is_conflict = True
                it2.is_conflict = True
                msg = f"时间冲突：[{it1.time_str}] {it1.title} 与 [{it2.time_str}] {it2.title} 存在重叠时段"
                if msg not in conflicts:
                    conflicts.append(msg)
    return conflicts


def build_timeline(*, target_date: date | None = None, offline: bool = False) -> TimelineReport:
    """构建指定日期（默认今天）的全局时空编排报告。

    支持离线优先（SWR 降级），无网环境下自动秒出。
    """
    now_date = target_date or date.today()
    date_str = now_date.strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now_date.weekday()]
    full_date_title = f"{date_str} {weekday_cn}"

    items: list[TimelineItem] = []
    is_stale = False
    stale_reasons = []

    # 1. 校历与学期周次
    term_info = "学期周次获取中..."
    try:
        from westlake_survival import calendar

        cal_data, meta = fetch_with_swr(
            "calendar",
            "full",
            lambda: calendar.load(),
            offline=offline,
        )
        if meta.get("is_stale"):
            is_stale = True
        sem = cal_data.semester_of(now_date)
        if sem:
            week_num = sem.week_of(now_date)
            term_info = f"{sem.name} 第 {week_num} 周" if week_num else sem.name
            holiday = sem.holiday_on(now_date)
            if holiday:
                items.append(
                    TimelineItem(
                        time_str="全天",
                        sort_time="00:00",
                        category="holiday",
                        title=f"校历假期：{holiday.name}",
                        location="全校",
                        status="假期",
                    )
                )
        else:
            term_info = "非教学期"
    except Exception as exc:
        stale_reasons.append(f"校历: {exc}")
        term_info = "西湖大学校历（离线）"

    # 2. 课表（SIS / AMS 融合）
    try:
        from westlake_survival.sis.client import sis
        from westlake_survival.sis.pages import get_schedule_rows

        def _fetch_schedule():
            client = sis()
            return get_schedule_rows(client)

        rows, meta = fetch_with_swr("sis", "schedule", _fetch_schedule, offline=offline)
        if meta.get("is_stale"):
            is_stale = True

        today_weekday = now_date.weekday() + 1
        for row in rows or []:
            if row.get("weekday") == today_weekday:
                time_range = str(row.get("time") or "").strip()
                sort_t = time_range.split("-")[0] if "-" in time_range else "08:00"
                items.append(
                    TimelineItem(
                        time_str=time_range or "时间待定",
                        sort_time=sort_t,
                        category="course",
                        title=str(row.get("name") or "课程"),
                        location=str(row.get("location") or "待定教室"),
                        status="已选课程",
                        details=f"课程代码: {row.get('course') or '—'}",
                    )
                )
    except Exception as exc:
        stale_reasons.append(f"课表: {exc}")

    # 3. Canvas 待办与作业截止
    try:
        from westlake_survival.canvas import canvas

        def _fetch_deadlines():
            client = canvas()
            res = []
            for a in client.upcoming_deadlines(limit=8):
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
            is_stale = True

        for d in deadlines_raw or []:
            due_at_str = d.get("due_at")
            if due_at_str:
                try:
                    dt = datetime.fromisoformat(due_at_str)
                    # 检查是否在未来 24 小时或属于今天
                    if dt.date() == now_date:
                        items.append(
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
        stale_reasons.append(f"Canvas: {exc}")

    # 4. 预约中心的场地预约
    try:
        from westlake_survival import booking

        def _fetch_bookings():
            return [b.to_dict() for b in booking.my_bookings()]

        b_rows, meta = fetch_with_swr("booking", "mine", _fetch_bookings, offline=offline)
        if meta.get("is_stale"):
            is_stale = True

        for b in b_rows or []:
            if b.get("date") == date_str and b.get("state") not in ("3", "取消"):
                start_t = b.get("start", "")
                end_t = b.get("end", "")
                items.append(
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
        stale_reasons.append(f"预约: {exc}")

    # 5. 班车接驳建议（根据全天最早课程/最早预约自动推荐）
    try:
        from westlake_survival.transit import next_bus

        # 查找今天 09:00 前是否有课
        morning_events = [it for it in items if it.sort_time < "10:00" and it.category == "course"]
        if morning_events:
            nb = next_bus()
            if nb:
                items.append(
                    TimelineItem(
                        time_str="推荐早班车",
                        sort_time="07:30",
                        category="transit",
                        title=f"接驳班车建议: 下班车 {nb.departure_time}",
                        location=f"{nb.route} ({nb.from_stop}→{nb.to_stop})",
                        status="班车通勤",
                        details="预留从容抵达与进教室时间",
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
