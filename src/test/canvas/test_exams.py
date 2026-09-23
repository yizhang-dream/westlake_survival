"""考试安排（quizzes / exam_events / exams）测试（全部离线）。

fixture 按 Canvas 官方 REST API 文档的 JSON 形状构造：``assignments``
（含 ``submission_types: ["online_quiz"]`` 的测验型与普通作业）与
``calendar_events``（``type=event``，用 ``context_code`` 标注归属）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from westlake_survival.canvas import CanvasClient
from westlake_survival.canvas.client import PER_PAGE
from westlake_survival.canvas.models import (
    CHINA_TZ,
    KIND_CALENDAR_EVENT,
    KIND_QUIZ,
    ExamEvent,
    QuizItem,
)
from westlake_survival.exceptions import AuthError

BASE = "https://canvas.example.edu/api/v1"

#: 测验型 assignment（Canvas ``GET /courses/:id/assignments`` 形状）。
QUIZ_ASSIGNMENT = {
    "id": 101,
    "course_id": 42,
    "name": "期末考试（在线测验）",
    "description": "<p>闭卷</p>",
    "due_at": "2026-12-28T02:00:00Z",
    "points_possible": 100.0,
    "submission_types": ["online_quiz"],
    "html_url": "https://canvas.example.edu/courses/42/assignments/101",
    "locked_for_user": False,
}

#: 普通 assignment（应被 quizzes 过滤掉）。
PLAIN_ASSIGNMENT = {
    "id": 102,
    "course_id": 42,
    "name": "第 1 次作业",
    "due_at": "2026-10-01T15:59:59Z",
    "submission_types": ["online_upload"],
    "html_url": "https://canvas.example.edu/courses/42/assignments/102",
}

#: exam 型 calendar_event（Canvas ``GET /calendar_events`` 形状）。
EXAM_CALENDAR_EVENT = {
    "id": 9001,
    "title": "期中考试",
    "start_at": "2026-11-10T01:00:00Z",
    "end_at": "2026-11-10T03:00:00Z",
    "all_day": False,
    "context_code": "course_42",
    "html_url": "https://canvas.example.edu/calendar?event_id=9001",
}


class FakeResponse:
    """最小 requests.Response 替身（json / links / text）。"""

    def __init__(self, status_code: int = 200, json_data=None, *, headers=None, text=None):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self._text = text if text is not None else json.dumps(json_data)

    @property
    def text(self) -> str:
        return self._text

    @property
    def links(self) -> dict:
        return {}

    def json(self):
        return self._json_data


class RoutedSession:
    """按 URL 片段路由响应的假 Session，记录所有请求。"""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return FakeResponse(200, [])


def make_client(session) -> CanvasClient:
    return CanvasClient(token="tok", session=session, base_url=BASE)


def _at(text: str):
    from westlake_survival.canvas.models import parse_datetime

    return parse_datetime(text)


# ----------------------------------------------------------------------
# 模型：JSON 形状与容错
# ----------------------------------------------------------------------
def test_quiz_item_from_json_maps_fields_and_timezone():
    quiz = QuizItem.from_json(QUIZ_ASSIGNMENT)
    assert quiz.id == 101 and quiz.course_id == 42
    assert quiz.title == "期末考试（在线测验）"
    assert quiz.url == QUIZ_ASSIGNMENT["html_url"]
    assert quiz.kind == KIND_QUIZ
    # 02:00 UTC -> 10:00 +08:00
    assert quiz.due_at is not None
    assert quiz.due_at.tzinfo == CHINA_TZ
    assert quiz.due_at.hour == 10


def test_quiz_item_tolerates_missing_fields():
    empty = QuizItem.from_json({})
    assert empty.id is None and empty.title is None and empty.due_at is None
    assert QuizItem.from_json(None).kind == KIND_QUIZ


def test_exam_event_from_json_parses_context_code_and_url_fallback():
    event = ExamEvent.from_json(EXAM_CALENDAR_EVENT)
    assert event.id == 9001 and event.course_id == 42  # 由 context_code 解析
    assert event.title == "期中考试"
    assert event.start_at is not None and event.start_at.hour == 9  # 01:00 UTC -> 09:00
    assert event.end_at is not None and event.end_at.hour == 11
    assert event.all_day is False
    assert event.kind == KIND_CALENDAR_EVENT
    assert event.url == EXAM_CALENDAR_EVENT["html_url"]


def test_exam_event_url_falls_back_to_url_and_ignores_non_course_context():
    event = ExamEvent.from_json(
        {"id": 1, "title": "x", "context_code": "user_7", "url": "https://x/cal"}
    )
    assert event.course_id is None
    assert event.url == "https://x/cal"
    assert ExamEvent.from_json({}).start_at is None


# ----------------------------------------------------------------------
# quizzes
# ----------------------------------------------------------------------
def test_quizzes_filters_online_quiz_only():
    session = RoutedSession({"/assignments": FakeResponse(200, [QUIZ_ASSIGNMENT, PLAIN_ASSIGNMENT])})
    client = make_client(session)
    quizzes = client.quizzes(42)
    assert [q.id for q in quizzes] == [101]
    url, params = session.calls[0]
    assert url == f"{BASE}/courses/42/assignments"
    assert params["per_page"] == PER_PAGE


def test_quizzes_empty_list_returns_empty():
    session = RoutedSession({"/assignments": FakeResponse(200, [])})
    assert make_client(session).quizzes(42) == []


def test_quizzes_across_all_active_courses_fills_course_id():
    session = RoutedSession(
        {
            "/courses/42/assignments": FakeResponse(200, [QUIZ_ASSIGNMENT]),
            "/courses/7/assignments": FakeResponse(
                200, [{**QUIZ_ASSIGNMENT, "id": 201, "course_id": None, "name": "小测"}]
            ),
            "/courses": FakeResponse(200, [{"id": 42}, {"id": 7}]),
        }
    )
    client = make_client(session)
    quizzes = client.quizzes()
    assert sorted(q.id for q in quizzes) == [101, 201]
    by_id = {q.id: q for q in quizzes}
    assert by_id[201].course_id == 7  # 从调用上下文补全


# ----------------------------------------------------------------------
# exam_events
# ----------------------------------------------------------------------
def test_exam_events_requests_type_event_with_context_code():
    session = RoutedSession({"/calendar_events": FakeResponse(200, [EXAM_CALENDAR_EVENT])})
    client = make_client(session)
    events = client.exam_events(42)
    assert [e.id for e in events] == [9001]
    url, params = session.calls[0]
    assert url == f"{BASE}/calendar_events"
    assert params["type"] == "event"
    assert params["context_codes[]"] == "course_42"
    assert params["per_page"] == PER_PAGE


def test_exam_events_all_contexts_when_course_id_none():
    session = RoutedSession({"/calendar_events": FakeResponse(200, [EXAM_CALENDAR_EVENT])})
    client = make_client(session)
    events = client.exam_events()
    assert len(events) == 1
    _, params = session.calls[0]
    assert "context_codes[]" not in params


# ----------------------------------------------------------------------
# exams（合并 + 排序 + --days 过滤）
# ----------------------------------------------------------------------
def test_exams_merges_quizzes_and_events_sorted():
    client = make_client(MagicMock())
    client.quizzes = lambda course_id=None: [
        QuizItem(id=101, title="期末", due_at=_at("2026-12-28T02:00:00Z"))
    ]
    client.exam_events = lambda course_id=None: [
        ExamEvent(id=9001, title="期中", start_at=_at("2026-11-10T01:00:00Z"))
    ]
    items = client.exams()
    assert [i.title for i in items] == ["期中", "期末"]  # 11 月在前
    assert {i.kind for i in items} == {KIND_QUIZ, KIND_CALENDAR_EVENT}


def test_exams_days_filters_window_and_drops_undated():
    now = datetime.now(CHINA_TZ)
    client = make_client(MagicMock())
    client.quizzes = lambda course_id=None: [
        QuizItem(id=1, title="soon", due_at=now + timedelta(days=2)),
        QuizItem(id=2, title="far", due_at=now + timedelta(days=40)),
        QuizItem(id=3, title="undated", due_at=None),
        QuizItem(id=4, title="past", due_at=now - timedelta(days=3)),
    ]
    client.exam_events = lambda course_id=None: [
        ExamEvent(id=5, title="event-soon", start_at=now + timedelta(days=1)),
    ]
    items = client.exams(days=7)
    assert [i.title for i in items] == ["event-soon", "soon"]


def test_exams_without_days_keeps_all_and_sorts_undated_last():
    client = make_client(MagicMock())
    client.quizzes = lambda course_id=None: [
        QuizItem(id=1, title="undated", due_at=None),
        QuizItem(id=2, title="later", due_at=_at("2027-01-01T00:00:00Z")),
    ]
    client.exam_events = lambda course_id=None: [
        ExamEvent(id=3, title="earlier", start_at=_at("2026-11-01T00:00:00Z")),
    ]
    assert [i.title for i in client.exams()] == ["earlier", "later", "undated"]


# ----------------------------------------------------------------------
# 错误映射：新端点走同一套 401 处理
# ----------------------------------------------------------------------
@pytest.mark.parametrize("call", ["quizzes", "exam_events"])
def test_new_exam_endpoints_map_401_to_auth_error(call):
    session = MagicMock()
    session.get.return_value = FakeResponse(401, {"errors": [{"message": "invalid"}]})
    client = make_client(session)
    with pytest.raises(AuthError) as excinfo:
        getattr(client, call)(42)
    assert "401" in str(excinfo.value)


# ----------------------------------------------------------------------
# CLI：westlake canvas exams
# ----------------------------------------------------------------------
def test_cli_canvas_exams_renders_table(monkeypatch):
    """``westlake canvas exams`` 表格输出 时间/名称/类型/链接。"""
    from click.testing import CliRunner

    import westlake_survival.canvas as canvas_pkg
    from westlake_survival.cli import cli

    client = make_client(MagicMock())
    client.quizzes = lambda course_id=None: [
        QuizItem(id=101, title="期末考试", due_at=_at("2099-12-28T02:00:00Z"), url="u1")
    ]
    client.exam_events = lambda course_id=None: [
        ExamEvent(id=9001, title="期中考试", start_at=_at("2099-11-10T01:00:00Z"), url="u2")
    ]
    monkeypatch.setattr(canvas_pkg, "canvas", lambda token=None: client)

    result = CliRunner().invoke(cli, ["canvas", "exams"])
    assert result.exit_code == 0, result.stderr
    assert "期中考试" in result.output and "测验" in result.output
    assert "2099-11-10 09:00" in result.output
    assert "2099-12-28 10:00" in result.output


def test_cli_canvas_exams_rejects_negative_days(monkeypatch):
    from click.testing import CliRunner

    import westlake_survival.canvas as canvas_pkg
    from westlake_survival.cli import cli

    client = make_client(MagicMock())
    client.exams = lambda days=None: []
    monkeypatch.setattr(canvas_pkg, "canvas", lambda token=None: client)
    result = CliRunner().invoke(cli, ["canvas", "exams", "--days", "-1"])
    assert result.exit_code == 2

