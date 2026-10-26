"""Canvas (Instructure LMS) 数据模型。

约定与 sustech_survival 的 ``bb`` 模块一致：

- 每个模型都是 :func:`dataclasses.dataclass`，字段顺序贴近 Canvas API
  的 JSON 字段名，方便对照。
- 每个模型提供 ``from_json`` 类方法，**容忍缺字段与 None**：缺失字段
  落到默认值，不会抛 KeyError。
- 时间字符串统一解析为 ``Asia/Shanghai`` 时区的 aware ``datetime``。
  Canvas 返回的是 ISO8601，可能带 ``Z`` 后缀（UTC），本模块会先转成
  ``+00:00`` 再换算到中国时区。

模型本身只做转换，不发请求；请求逻辑见 :mod:`westlake_survival.canvas.client`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _load_china_tz():
    """加载 ``Asia/Shanghai`` 时区。

    首选标准库 :class:`zoneinfo.ZoneInfo`；Windows / 精简镜像上系统没有
    IANA 时区库（``tzdata`` 未随解释器提供）时，退回 ``python-dateutil``
    自带的 IANA 数据库（本就是本项目依赖），再不行退回固定 +08:00。
    中国不实行夏令时，三者语义一致。
    """
    try:
        return ZoneInfo("Asia/Shanghai")
    except ZoneInfoNotFoundError:
        try:
            from dateutil import tz as _dateutil_tz

            zone = _dateutil_tz.gettz("Asia/Shanghai")
            if zone is not None:
                return zone
        except Exception:  # pragma: no cover - 防御性
            pass
        return timezone(timedelta(hours=8))


#: 全库统一的中国时区（naive 输入按 UTC 解释后换算到此时区）。
CHINA_TZ = _load_china_tz()


def parse_datetime(value: Any) -> datetime | None:
    """把 Canvas 的时间字段解析为 ``CHINA_TZ`` 的 aware datetime。

    - ``None`` / 空字符串 / 无法解析的字符串 → ``None``（容忍脏数据）。
    - 带 ``Z`` 后缀的 UTC 时间会先规范成 ``+00:00`` 再换算时区。
    - naive 时间按 UTC 处理（Canvas 不加时区时实际就是 UTC）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text[-1] in ("Z", "z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CHINA_TZ)


def _as_dict(data: Any) -> Mapping[str, Any]:
    """把 API 返回项规整为 Mapping；非 Mapping 时返回空字典。"""
    return data if isinstance(data, Mapping) else {}


@dataclass
class User:
    """当前用户（``GET /users/self``）。"""

    id: int | None = None
    name: str | None = None
    login_id: str | None = None
    primary_email: str | None = None

    @classmethod
    def from_json(cls, data: Any) -> "User":
        obj = _as_dict(data)
        return cls(
            id=obj.get("id"),
            name=obj.get("name"),
            login_id=obj.get("login_id"),
            primary_email=obj.get("primary_email"),
        )


@dataclass
class Course:
    """课程。``term_name`` 可能来自顶层或嵌套的 ``term.name``。"""

    id: int | None = None
    name: str | None = None
    course_code: str | None = None
    term_name: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_public: bool | None = None

    @classmethod
    def from_json(cls, data: Any) -> "Course":
        obj = _as_dict(data)
        term_name = obj.get("term_name")
        if term_name is None:
            term = obj.get("term")
            if isinstance(term, Mapping):
                term_name = term.get("name")
        return cls(
            id=obj.get("id"),
            name=obj.get("name"),
            course_code=obj.get("course_code"),
            term_name=term_name,
            start_at=parse_datetime(obj.get("start_at")),
            end_at=parse_datetime(obj.get("end_at")),
            is_public=obj.get("is_public"),
        )


@dataclass
class Assignment:
    """作业。``due_at`` 为 ``None`` 表示无截止日期。"""

    id: int | None = None
    course_id: int | None = None
    name: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    points_possible: float | None = None
    submission_types: list[str] = field(default_factory=list)
    html_url: str | None = None
    locked_for_user: bool | None = None

    @classmethod
    def from_json(cls, data: Any) -> "Assignment":
        obj = _as_dict(data)
        submission_types = obj.get("submission_types")
        if not isinstance(submission_types, list):
            submission_types = []
        return cls(
            id=obj.get("id"),
            course_id=obj.get("course_id"),
            name=obj.get("name"),
            description=obj.get("description"),
            due_at=parse_datetime(obj.get("due_at")),
            points_possible=obj.get("points_possible"),
            submission_types=[str(item) for item in submission_types],
            html_url=obj.get("html_url"),
            locked_for_user=obj.get("locked_for_user"),
        )


@dataclass
class TodoItem:
    """Canvas 待办（``GET /users/self/todo``）。

    ``type`` 是 Canvas 的待办类型（``submitting`` / ``grading`` 等），
    ``course`` 来自 ``context_name``；标题与截止时间优先取内嵌
    ``assignment``。``due_at`` 与其它模型一致，统一换算到 ``CHINA_TZ``。
    """

    type: str = ""
    course: str | None = None
    title: str | None = None
    due_at: datetime | None = None
    url: str | None = None

    @classmethod
    def from_json(cls, data: Any) -> "TodoItem":
        obj = _as_dict(data)
        assignment = _as_dict(obj.get("assignment"))
        return cls(
            type=str(obj.get("type") or ""),
            course=obj.get("context_name"),
            title=assignment.get("name") or obj.get("title"),
            due_at=parse_datetime(assignment.get("due_at") or obj.get("due_at")),
            url=obj.get("html_url") or assignment.get("html_url"),
        )


#: 判断作业是否为测验（quiz）的 submission_type 值。
QUIZ_SUBMISSION_TYPE = "online_quiz"

#: 三种 API 可提交的 submission_type 值（文件上传 / 文本 / 链接）。
SUBMISSION_TYPE_UPLOAD = "online_upload"
SUBMISSION_TYPE_TEXT = "online_text_entry"
SUBMISSION_TYPE_URL = "online_url"

#: 日历事件类型标识。
KIND_QUIZ = "quiz"
KIND_CALENDAR_EVENT = "calendar-event"


@dataclass
class QuizItem:
    """测验型作业（``GET /courses/:id/assignments`` 中 ``submission_types``
    含 ``online_quiz`` 的条目）。

    Canvas 没有独立的「考试」对象，期末考试通常挂在一个 ``online_quiz``
    型作业上，因此用该信号近似考试安排。字段沿用 :class:`Assignment`，
    另加 :attr:`kind` 便于与日历事件统一排序展示。
    """

    id: int | None = None
    course_id: int | None = None
    title: str | None = None
    due_at: datetime | None = None
    url: str | None = None
    kind: str = KIND_QUIZ

    @classmethod
    def from_json(cls, data: Any) -> "QuizItem":
        obj = _as_dict(data)
        return cls(
            id=obj.get("id"),
            course_id=obj.get("course_id"),
            title=obj.get("name"),
            due_at=parse_datetime(obj.get("due_at")),
            url=obj.get("html_url"),
            kind=KIND_QUIZ,
        )


@dataclass
class ExamEvent:
    """课程日历事件（``GET /calendar_events``）。

    ``start_at`` / ``end_at`` 为事件起止时间；``all_day`` 为全天事件时
    Canvas 只给日期。``url`` 优先取 ``html_url``，缺失时回落到 ``url``。
    Canvas 的事件用 ``context_code``（如 ``course_1234``）标注归属，
    这里解析为 :attr:`course_id`；非 course context（如 ``user_…``）留空。
    """

    id: int | None = None
    course_id: int | None = None
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    url: str | None = None
    kind: str = KIND_CALENDAR_EVENT

    @classmethod
    def from_json(cls, data: Any) -> "ExamEvent":
        obj = _as_dict(data)
        course_id = obj.get("course_id")
        if course_id is None:
            context_code = obj.get("context_code")
            if isinstance(context_code, str) and context_code.startswith("course_"):
                try:
                    course_id = int(context_code.split("_", 1)[1])
                except ValueError:
                    course_id = None
        return cls(
            id=obj.get("id"),
            course_id=course_id,
            title=obj.get("title"),
            start_at=parse_datetime(obj.get("start_at")),
            end_at=parse_datetime(obj.get("end_at")),
            all_day=obj.get("all_day"),
            url=obj.get("html_url") or obj.get("url"),
            kind=KIND_CALENDAR_EVENT,
        )


@dataclass
class File:
    """课程文件（``GET /courses/:id/files`` / ``GET /files/:id``）。"""

    id: int | None = None
    display_name: str | None = None
    size: int | None = None
    url: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None

    @classmethod
    def from_json(cls, data: Any) -> "File":
        obj = _as_dict(data)
        return cls(
            id=obj.get("id"),
            display_name=obj.get("display_name") or obj.get("filename"),
            size=obj.get("size"),
            url=obj.get("url"),
            created_at=parse_datetime(obj.get("created_at")),
            modified_at=parse_datetime(obj.get("modified_at")),
        )


@dataclass
class Submission:
    """作业提交（``POST .../submissions`` / ``GET .../submissions/self``）。

    ``workflow_state`` 常见值：``submitted``（已提交待评分）、``graded``
    （已评分）、``unsubmitted``（从未提交）。文件提交的附件在
    :attr:`attachments`（:class:`File` 列表）；文本/链接提交分别在
    :attr:`body` / :attr:`url`。
    """

    id: int | None = None
    assignment_id: int | None = None
    user_id: int | None = None
    workflow_state: str | None = None
    submitted_at: datetime | None = None
    late: bool | None = None
    score: float | None = None
    body: str | None = None
    url: str | None = None
    preview_url: str | None = None
    attachments: list[File] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: Any) -> "Submission":
        obj = _as_dict(data)
        raw_attachments = obj.get("attachments")
        attachments: list[File] = []
        if isinstance(raw_attachments, list):
            attachments = [File.from_json(item) for item in raw_attachments]
        return cls(
            id=obj.get("id"),
            assignment_id=obj.get("assignment_id"),
            user_id=obj.get("user_id"),
            workflow_state=obj.get("workflow_state"),
            submitted_at=parse_datetime(obj.get("submitted_at")),
            late=obj.get("late"),
            score=obj.get("score"),
            body=obj.get("body"),
            url=obj.get("url"),
            preview_url=obj.get("preview_url"),
            attachments=attachments,
        )


@dataclass
class Announcement:
    """课程公告（``GET /courses/:id/discussion_topics?only_announcements=true``）。"""

    id: int | None = None
    course_id: int | None = None
    title: str | None = None
    message: str | None = None
    posted_at: datetime | None = None
    html_url: str | None = None

    @classmethod
    def from_json(cls, data: Any) -> "Announcement":
        obj = _as_dict(data)
        return cls(
            id=obj.get("id"),
            course_id=obj.get("course_id"),
            title=obj.get("title"),
            message=obj.get("message"),
            posted_at=parse_datetime(obj.get("posted_at")),
            html_url=obj.get("html_url"),
        )


__all__ = [
    "CHINA_TZ",
    "KIND_CALENDAR_EVENT",
    "KIND_QUIZ",
    "QUIZ_SUBMISSION_TYPE",
    "SUBMISSION_TYPE_TEXT",
    "SUBMISSION_TYPE_UPLOAD",
    "SUBMISSION_TYPE_URL",
    "Announcement",
    "Assignment",
    "Course",
    "ExamEvent",
    "File",
    "QuizItem",
    "Submission",
    "TodoItem",
    "User",
    "parse_datetime",
]
