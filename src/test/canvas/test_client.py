"""CanvasClient 测试（全部离线，mock Session/Response）。

覆盖：token 三级解析、分页、错误映射、upcoming_deadlines 合并排序、
download_file 流式写入。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from westlake_survival.canvas import CanvasClient
from westlake_survival.canvas.client import (
    CANVAS_BASE,
    PER_PAGE,
    TOKEN_ENV_VAR,
    resolve_token,
    token_file_path,
)
from westlake_survival.canvas.models import Assignment, Course, parse_datetime
from westlake_survival.exceptions import AuthError, NotFound, ParseError, WestlakeError

BASE = "https://canvas.example.edu/api/v1"


class FakeResponse:
    """最小化的 requests.Response 替身，支持 .json()/.links/.iter_content。"""

    def __init__(
        self,
        status_code: int = 200,
        json_data=None,
        *,
        headers: dict | None = None,
        text: str | None = None,
        chunks: list[bytes] | None = None,
        json_error: bool = False,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self._text = text if text is not None else ("" if json_data is None else json.dumps(json_data))
        self._chunks = chunks or []
        self._json_error = json_error
        self.closed = False

    @property
    def text(self) -> str:
        return self._text

    @property
    def links(self) -> dict:
        raw = self.headers.get("Link")
        if not raw:
            return {}
        result: dict = {}
        for part in raw.split(","):
            segments = [seg.strip() for seg in part.split(";")]
            url_part = segments[0]
            if not (url_part.startswith("<") and url_part.endswith(">")):
                continue
            url = url_part[1:-1]
            for seg in segments[1:]:
                key, _, value = seg.partition("=")
                if key.strip() == "rel":
                    result[value.strip().strip('"')] = {"url": url}
        return result

    def json(self):
        if self._json_error:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._json_data

    def iter_content(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            yield chunk

    def close(self) -> None:
        self.closed = True


def make_client(session, token="tok", base_url=BASE) -> CanvasClient:
    return CanvasClient(token=token, session=session, base_url=base_url)


# ----------------------------------------------------------------------
# token 三级解析
# ----------------------------------------------------------------------
def test_token_explicit_argument_wins(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "from-env")
    assert resolve_token("from-arg") == "from-arg"


def test_token_from_env_when_no_argument(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "  from-env  ")
    assert resolve_token(None) == "from-env"


def test_token_from_file_when_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))
    (tmp_path / "canvas_token.txt").write_text("file-token\nsecond-line\n", encoding="utf-8")
    assert token_file_path() == tmp_path / "canvas_token.txt"
    assert resolve_token(None) == "file-token"


def test_token_missing_raises_auth_error(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))
    assert resolve_token(None) is None
    with pytest.raises(AuthError) as excinfo:
        CanvasClient(token=None)
    assert "访问令牌" in str(excinfo.value)


def test_empty_file_does_not_yield_token(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))
    (tmp_path / "canvas_token.txt").write_text("\n", encoding="utf-8")
    assert resolve_token(None) is None


# ----------------------------------------------------------------------
# 错误映射
# ----------------------------------------------------------------------
def test_401_maps_to_auth_error():
    session = MagicMock()
    session.get.return_value = FakeResponse(401, {"errors": [{"message": "invalid"}]})
    client = make_client(session)
    with pytest.raises(AuthError) as excinfo:
        client.me()
    assert "401" in str(excinfo.value)


def test_404_maps_to_not_found():
    session = MagicMock()
    session.get.return_value = FakeResponse(
        404, {"errors": [{"message": "The specified resource does not exist."}]}
    )
    client = make_client(session)
    with pytest.raises(NotFound):
        client.get_course(999)


def test_other_error_maps_to_westlake_error_with_body_snippet():
    session = MagicMock()
    long_body = "x" * 500
    session.get.return_value = FakeResponse(500, text=long_body)
    client = make_client(session)
    with pytest.raises(WestlakeError) as excinfo:
        client.list_courses()
    message = str(excinfo.value)
    assert "500" in message
    # 只附带前 200 字符
    assert message.count("x") == 200


def test_invalid_json_maps_to_parse_error():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, text="<html>not json</html>", json_error=True)
    client = make_client(session)
    with pytest.raises(ParseError):
        client.me()


# ----------------------------------------------------------------------
# 请求头 / 分页
# ----------------------------------------------------------------------
def test_request_sends_bearer_and_per_page():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, [])
    client = make_client(session)
    client.list_courses()

    _, kwargs = session.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["params"]["per_page"] == PER_PAGE
    assert kwargs["params"]["enrollment_state"] == "active"
    assert kwargs["timeout"] is not None
    assert session.get.call_args.args[0] == f"{BASE}/courses"


def test_pagination_follows_link_next_header():
    session = MagicMock()
    next_url = f"{BASE}/courses?page=2"
    session.get.side_effect = [
        FakeResponse(
            200,
            [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
            headers={"Link": f'<{next_url}>; rel="next"'},
        ),
        FakeResponse(200, [{"id": 3, "name": "C"}]),
    ]
    client = make_client(session)
    courses = client.list_courses()

    assert [c.id for c in courses] == [1, 2, 3]
    assert session.get.call_count == 2
    # 第二页用完整 URL，且不再重复带 per_page
    second_call = session.get.call_args_list[1]
    assert second_call.args[0] == next_url
    assert second_call.kwargs["params"] is None


def test_pagination_stops_when_next_url_cycles_back():
    """两页互相指向对方：visited 集合应立即终止，不得死循环。"""
    session = MagicMock()
    start_url = f"{BASE}/courses"
    url_b = f"{BASE}/courses?page=2"
    session.get.side_effect = [
        FakeResponse(200, [{"id": 1, "name": "A"}], headers={"Link": f'<{url_b}>; rel="next"'}),
        # 第二页的 next 指回第一页，形成两页互相指向的环
        FakeResponse(
            200, [{"id": 2, "name": "B"}], headers={"Link": f'<{start_url}>; rel="next"'}
        ),
    ]
    client = make_client(session)
    courses = client.list_courses()

    assert [c.id for c in courses] == [1, 2]
    assert session.get.call_count == 2


def test_pagination_stops_when_next_is_self_reference():
    """next 指向当前页自身：只发一次请求即终止。"""
    session = MagicMock()
    self_url = f"{BASE}/courses"
    session.get.return_value = FakeResponse(
        200, [{"id": 1, "name": "A"}], headers={"Link": f'<{self_url}>; rel="next"'}
    )
    client = make_client(session)
    courses = client.list_courses()

    assert [c.id for c in courses] == [1]
    assert session.get.call_count == 1


def test_list_assignments_passes_bucket_and_include_future():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, [])
    client = make_client(session)
    client.list_assignments(42, bucket="upcoming", include_future=True)
    _, kwargs = session.get.call_args
    assert kwargs["params"]["bucket"] == "upcoming"
    assert kwargs["params"]["include_future"] == "true"
    assert session.get.call_args.args[0] == f"{BASE}/courses/42/assignments"


# ----------------------------------------------------------------------
# upcoming_deadlines
# ----------------------------------------------------------------------
def _dt(text: str):
    return parse_datetime(text)


def test_upcoming_deadlines_merges_sorts_and_skips_none():
    client = make_client(MagicMock())
    client.list_courses = lambda enrollment_state="active": [Course(id=1), Course(id=2)]

    def fake_assignments(course_id, *, bucket=None, include_future=False):
        assert bucket == "upcoming"
        if course_id == 1:
            return [
                Assignment(id=10, due_at=_dt("2026-10-02T00:00:00Z")),
                Assignment(id=11, due_at=None),  # 应被跳过
            ]
        return [Assignment(id=20, due_at=_dt("2026-10-01T00:00:00Z"))]

    client.list_assignments = fake_assignments
    result = client.upcoming_deadlines(limit=10)

    assert [a.id for a in result] == [20, 10]
    assert all(a.due_at is not None for a in result)
    # 补全 course_id
    assert [a.course_id for a in result] == [2, 1]


def test_upcoming_deadlines_respects_limit():
    client = make_client(MagicMock())
    client.list_courses = lambda enrollment_state="active": [Course(id=1)]
    client.list_assignments = lambda course_id, *, bucket=None, include_future=False: [
        Assignment(id=1, due_at=_dt("2026-10-01T00:00:00Z")),
        Assignment(id=2, due_at=_dt("2026-10-02T00:00:00Z")),
        Assignment(id=3, due_at=_dt("2026-10-03T00:00:00Z")),
    ]
    assert [a.id for a in client.upcoming_deadlines(limit=2)] == [1, 2]


# ----------------------------------------------------------------------
# download_file
# ----------------------------------------------------------------------
def test_download_file_streams_to_dest(tmp_path):
    session = MagicMock()
    meta = FakeResponse(200, {"id": 5, "url": "https://files.example/signed/a.bin"})
    content = FakeResponse(200, chunks=[b"abc", b"", b"def"])
    session.get.side_effect = [meta, content]

    client = make_client(session)
    dest = tmp_path / "sub" / "out.bin"
    result = client.download_file(5, dest)

    assert result == dest
    assert dest.read_bytes() == b"abcdef"
    # 元数据请求带 Authorization；内容请求不带（避免 token 泄漏给 CDN）
    meta_kwargs = session.get.call_args_list[0].kwargs
    assert meta_kwargs["headers"]["Authorization"] == "Bearer tok"
    content_kwargs = session.get.call_args_list[1].kwargs
    assert content_kwargs["stream"] is True
    assert "headers" not in content_kwargs
    assert content.closed is True


def test_download_file_without_url_raises_parse_error(tmp_path):
    session = MagicMock()
    session.get.return_value = FakeResponse(200, {"id": 5})
    client = make_client(session)
    with pytest.raises(ParseError):
        client.download_file(5, tmp_path / "x.bin")


# ----------------------------------------------------------------------
# list_announcements / get_course
# ----------------------------------------------------------------------
def test_list_announcements_sets_course_id():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, [{"id": 9, "title": "公告"}])
    client = make_client(session)
    items = client.list_announcements(7)
    assert items[0].course_id == 7
    _, kwargs = session.get.call_args
    assert kwargs["params"]["only_announcements"] == "true"
    assert session.get.call_args.args[0] == f"{BASE}/courses/7/discussion_topics"


def test_me_parses_user():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, {"id": 1, "name": "me", "login_id": "abc"})
    client = make_client(session)
    user = client.me()
    assert user.id == 1 and user.name == "me"
    assert session.get.call_args.args[0] == f"{BASE}/users/self"


def test_default_base_url_constant():
    assert CANVAS_BASE == "https://canvas.westlake.edu.cn/api/v1"
