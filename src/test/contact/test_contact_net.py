"""contact 网络层测试（离线，注入假 Session 与假响应）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from westlake_survival import contact
from westlake_survival.contact import CONTACT_URL, campuses, contacts
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError

FIXTURE_PATH = Path(__file__).parent / "fixture_contact.html"


class FakeResponse:
    """最小化 :class:`requests.Response` 替身。

    只有 ``content`` 与 ``headers``，**故意不提供可用的 ``text``**——真实页面无
    charset 头，``response.text`` 会乱码，模块必须走 ``content`` 解码。``text``
    属性返回 latin-1 乱码以模拟误用后果。
    """

    def __init__(
        self,
        body: bytes,
        *,
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        self.content = body
        self.status_code = status_code
        self.headers = headers or {}
        self.url = CONTACT_URL

    @property
    def text(self) -> str:
        return self.content.decode("latin-1")


class FakeSession:
    """记录调用参数的假 Session。"""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None):  # noqa: ANN001
        self.calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
        return self.response


@pytest.fixture
def fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """把缓存目录重定位到临时目录，避免污染真实 ~/.westlake_survival。"""
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))


def test_campuses_via_session(fixture_bytes, isolated_home) -> None:
    """``campuses`` 真走注入 session，且按 UTF-8 从 content 解码。"""
    session = FakeSession(FakeResponse(fixture_bytes))
    result = campuses(session=session, timeout=5.0)

    assert [c.name for c in result] == ["云谷", "云栖", "铜鉴湖"]
    assert session.calls[0]["url"] == CONTACT_URL
    assert session.calls[0]["timeout"] == 5.0
    assert session.calls[0]["headers"] == {}  # 首次无 ETag


def test_contacts_via_session(fixture_bytes, isolated_home) -> None:
    session = FakeSession(FakeResponse(fixture_bytes))
    result = contacts(session=session)
    assert len(result) == 3
    assert result[0].phones == ["0571-88996767", "0571-86886872"]


def test_etag_saved_and_replayed(fixture_bytes, isolated_home) -> None:
    """首次响应带 ETag 应写缓存，第二次带 ``If-None-Match``。"""
    first = FakeSession(FakeResponse(fixture_bytes, headers={"ETag": 'W/"abc"'}))
    campuses(session=first)

    second = FakeSession(FakeResponse(fixture_bytes))
    campuses(session=second)
    assert second.calls[0]["headers"] == {"If-None-Match": 'W/"abc"'}


def test_not_modified_uses_cache(fixture_bytes, isolated_home) -> None:
    """服务器 304 时用缓存正文，不重新解析响应体。"""
    campuses(session=FakeSession(FakeResponse(fixture_bytes, headers={"ETag": '"v1"'})))

    empty = FakeResponse(b"", status_code=304, headers={"ETag": '"v1"'})
    session = FakeSession(empty)
    result = campuses(session=session)
    assert [c.name for c in result] == ["云谷", "云栖", "铜鉴湖"]


def test_refresh_sends_unconditional_get(fixture_bytes, isolated_home) -> None:
    """``refresh=True`` 清缓存后首发无条件请求。"""
    campuses(session=FakeSession(FakeResponse(fixture_bytes, headers={"ETag": '"v1"'})))
    session = FakeSession(FakeResponse(fixture_bytes, headers={"ETag": '"v2"'}))
    campuses(refresh=True, session=session)
    assert session.calls[0]["headers"] == {}


def test_network_error_maps_to_westlake_error(isolated_home) -> None:
    class BoomSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("断网")

    with pytest.raises(WestlakeError, match="请求失败"):
        campuses(session=BoomSession())


def test_timeout_maps_to_westlake_error(isolated_home) -> None:
    class TimeoutSession:
        def get(self, *args, **kwargs):
            raise requests.Timeout("超时")

    with pytest.raises(WestlakeError, match="超时"):
        campuses(session=TimeoutSession())


def test_offcampus_403_maps(isolated_home) -> None:
    blocked = FakeResponse(
        b"Access forbidden, please contact administrator",
        status_code=403,
        headers={"Content-Type": "text/html"},
    )
    with pytest.raises(OffCampusError):
        campuses(session=FakeSession(blocked))


def test_http_500_maps_to_parse_error(isolated_home) -> None:
    with pytest.raises(ParseError, match="HTTP 500"):
        campuses(session=FakeSession(FakeResponse(b"oops", status_code=500)))


def test_empty_body_maps_to_parse_error(isolated_home) -> None:
    with pytest.raises(ParseError, match="空响应体"):
        campuses(session=FakeSession(FakeResponse(b"   \n")))


def test_non_utf8_maps_to_parse_error(isolated_home) -> None:
    with pytest.raises(ParseError, match="UTF-8"):
        campuses(session=FakeSession(FakeResponse(b"\xff\xfe\xff")))


def test_missing_content_attribute(isolated_home) -> None:
    """响应连 content 都没有（用了 response.text 的替身）→ ParseError。"""

    class TextOnly:
        status_code = 200
        headers: dict = {}
        text = "…"

    class Sess:
        def get(self, *a, **k):
            return TextOnly()

    with pytest.raises(ParseError, match="content"):
        campuses(session=Sess())


def test_module_uses_content_not_text(fixture_bytes, isolated_home) -> None:
    """整体回归：解析结果与直接从 bytes 解码一致（若误用 .text 会乱码）。"""
    session = FakeSession(FakeResponse(fixture_bytes))
    result = campuses(session=session)
    assert result[0].address == "浙江省杭州市西湖区墩余路600号"
    assert "联系电话" not in result[0].address
