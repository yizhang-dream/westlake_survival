"""``westlake_survival.events`` 的离线解析与查询测试。

全部离线：fixture 是真实页面片段，网络层用 :class:`events_fakes.FakeSession`
打桩。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from events_fakes import FakeResponse, FakeSession
from westlake_survival.events import (
    EventDetail,
    EventItem,
    fetch_detail,
    load_events,
    parse_datetime,
    parse_detail,
    parse_events,
    upcoming,
)
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError


# --------------------------------------------------------------------------- #
# datetime 解析
# --------------------------------------------------------------------------- #
def test_parse_datetime_full_and_short() -> None:
    assert parse_datetime("2026-09-23 14:00:00") == datetime(2026, 9, 23, 14, 0)
    assert parse_datetime("2026-09-23 14:00") == datetime(2026, 9, 23, 14, 0)
    assert parse_datetime("2026/09/23 08:05:30") == datetime(2026, 9, 23, 8, 5, 30)


def test_parse_datetime_date_only_midnight() -> None:
    assert parse_datetime("2026-09-23") == datetime(2026, 9, 23, 0, 0)


def test_parse_datetime_invalid_returns_none() -> None:
    assert parse_datetime("") is None
    assert parse_datetime("无日期") is None
    assert parse_datetime("2026-13-40 10:00:00") is None


# --------------------------------------------------------------------------- #
# 列表解析
# --------------------------------------------------------------------------- #
def test_parse_events_from_fixture(fixture_list_text: str) -> None:
    items = parse_events(fixture_list_text)
    assert len(items) == 6
    first = items[0]
    assert isinstance(first, EventItem)
    assert first.title.startswith("西湖理学讲坛")
    assert first.date == datetime(2026, 9, 23, 14, 0)
    assert first.date_only == date(2026, 9, 23)
    assert first.time_range == "2026-09-23 14:00 - 2026-09-23 15:30"
    assert first.venue == "云谷校区E10-211"
    assert first.organizer == "理学院"
    assert first.event_type == "名家讲座"
    assert first.brand == ""
    assert first.url.endswith("/t20260916_69819.html")


def test_parse_events_ignores_function_callback(fixture_list_text: str) -> None:
    """组件块含 ``mounted: function () {}``，按键提取数组应不受影响。"""
    assert "mounted: function" in fixture_list_text
    items = parse_events(fixture_list_text)
    assert len(items) == 6


def test_parse_events_keeps_brand_and_short_range(fixture_list_text: str) -> None:
    items = parse_events(fixture_list_text)
    wemeet = next(i for i in items if i.brand == "WeMeet")
    assert wemeet.event_type == "名家讲座"
    assert wemeet.organizer == ""  # 该条 school 为空
    assert wemeet.time_range == "18:30-20:30"


def test_parse_events_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_events("<html>没有组件</html>")


def test_parse_events_missing_eventlist_raises() -> None:
    html = "<script>new events('#app', { mounted: function () {} });</script>"
    with pytest.raises(ParseError, match="eventList"):
        parse_events(html)


def test_parse_events_all_unparseable_raises() -> None:
    html = "<script>new events('#app', { eventList: [{title: '', date: ''}] });</script>"
    with pytest.raises(ParseError):
        parse_events(html)


def test_parse_events_skips_bad_entries_keeps_good() -> None:
    html = (
        "<script>new events('#app', { eventList: ["
        "{date: 'bad', title: 'x'},"
        "{date: '2026-09-23 10:00:00', title: '好条目'}"
        "] });</script>"
    )
    items = parse_events(html)
    assert [i.title for i in items] == ["好条目"]


# --------------------------------------------------------------------------- #
# 详情解析
# --------------------------------------------------------------------------- #
def test_parse_detail_from_fixture(fixture_detail_text: str) -> None:
    detail = parse_detail(fixture_detail_text, url="https://example.com/d.html")
    assert isinstance(detail, EventDetail)
    assert detail.title.startswith("西湖理学讲坛")
    assert detail.date_text == "2026-09-23 14:00:00"
    assert detail.time_text == "2026-09-23 14:00 - 2026-09-23 15:30"
    assert detail.venue == "云谷校区E10-211"
    assert detail.host == ""
    assert detail.audience == ""
    assert detail.category == "名家讲座"
    assert detail.content_html.startswith("<p>")
    assert detail.url == "https://example.com/d.html"


def test_parse_detail_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_detail("<html>无详情组件</html>")


def test_parse_detail_missing_left_raises() -> None:
    html = "<script>new eventsDetail('#app', { right: {title: 'x'} });</script>"
    with pytest.raises(ParseError, match="left"):
        parse_detail(html)


def test_parse_detail_title_falls_back_to_title_tag() -> None:
    html = (
        "<html><head><title>某讲座&nbsp;-&nbsp;西湖大学</title></head>"
        "<body><script>new eventsDetail('#app', { left: {Data: '2026-09-23'} });"
        "</script></body></html>"
    )
    assert parse_detail(html).title == "某讲座"


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _list_session(fixture_list_text: str, **kwargs) -> FakeSession:
    return FakeSession(
        lambda url, kw: FakeResponse(fixture_list_text, url=url, **kwargs)
    )


def test_load_events_decodes_bytes_not_latin1(
    isolated_home, fixture_list_text: str
) -> None:
    """响应头无 charset，必须走 content 字节路径（否则中文乱码）。"""
    session = _list_session(fixture_list_text)
    items = load_events(session=session)
    assert len(items) == 6
    assert items[0].title.startswith("西湖理学讲坛")


def test_load_events_uses_etag_cache(isolated_home, fixture_list_text: str) -> None:
    """首次带 ETag 存缓存；第二次带 If-None-Match 收到 304 时复用缓存正文。"""
    session = _list_session(fixture_list_text, headers={"ETag": 'W/"abc"'})
    assert len(load_events(session=session)) == 6

    session304 = FakeSession(
        lambda url, kw: FakeResponse(b"", status=304, url=url)
    )
    items = load_events(session=session304)
    assert len(items) == 6
    _, kwargs = session304.calls[0]
    assert kwargs["headers"].get("If-None-Match") == 'W/"abc"'


def test_load_events_http_500_raises_parse_error(isolated_home) -> None:
    session = FakeSession(lambda url, kw: FakeResponse(b"boom", status=500, url=url))
    with pytest.raises(ParseError):
        load_events(session=session)


def test_load_events_403_offcampus_marker(isolated_home) -> None:
    body = b"Access forbidden, please contact administrator"
    session = FakeSession(lambda url, kw: FakeResponse(body, status=403, url=url))
    with pytest.raises(OffCampusError):
        load_events(session=session)


def test_load_events_timeout_maps_to_westlake_error(isolated_home) -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.Timeout("timed out")

    with pytest.raises(WestlakeError) as excinfo:
        load_events(session=FakeSession(boom))
    assert "超时" in str(excinfo.value)


def test_fetch_detail_uses_content_bytes(isolated_home, fixture_detail_text: str) -> None:
    session = FakeSession(
        lambda url, kw: FakeResponse(fixture_detail_text, url=url)
    )
    detail = fetch_detail("https://example.com/d.html", session=session)
    assert detail.title.startswith("西湖理学讲坛")
    assert detail.url == "https://example.com/d.html"


def test_fetch_detail_empty_url_raises() -> None:
    with pytest.raises(ValueError):
        fetch_detail("")


def test_fetch_detail_connection_error_maps(isolated_home) -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.ConnectionError("no route to host")

    with pytest.raises(WestlakeError) as excinfo:
        fetch_detail("https://example.com/d.html", session=FakeSession(boom))
    assert "失败" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 过滤 / upcoming
# --------------------------------------------------------------------------- #
def test_load_events_filters_type(isolated_home, fixture_list_text: str) -> None:
    items = load_events(event_type="学术会议", session=_list_session(fixture_list_text))
    assert [i.title for i in items] == [
        "生命科学名师论坛 | Tanja Mittag: Emergent properties of biomolecular "
        "condensates determine their biochemical activities"
    ]


def test_load_events_filters_since_until(isolated_home, fixture_list_text: str) -> None:
    session = _list_session(fixture_list_text)
    only_22 = load_events(
        since=date(2026, 9, 22), until=date(2026, 9, 22), session=session
    )
    assert len(only_22) == 3
    assert all(i.date_only == date(2026, 9, 22) for i in only_22)

    from_23 = load_events(since=date(2026, 9, 23), session=session)
    assert len(from_23) == 1


def test_load_events_limit(isolated_home, fixture_list_text: str) -> None:
    items = load_events(limit=2, session=_list_session(fixture_list_text))
    assert len(items) == 2


def test_upcoming_window_boundaries(isolated_home, fixture_list_text: str) -> None:
    """upcoming 从今天起含今天；过期条目被排除，结果按时间升序。"""
    session = _list_session(fixture_list_text)
    # 以 9/21 为"今天"，14 天窗口应覆盖 fixture 里全部 6 条。
    items = upcoming(14, session=session, today=date(2026, 9, 21))
    assert len(items) == 6
    dates = [i.date for i in items]
    assert dates == sorted(dates)

    # 窗口只看今天（9/23）：只剩 9/23 那条，9/22 及更早的都已过期。
    today_only = upcoming(0, session=session, today=date(2026, 9, 23))
    assert [i.date_only for i in today_only] == [date(2026, 9, 23)]

    # 起点在 fixture 之后：无未来活动。
    assert upcoming(7, session=session, today=date(2026, 10, 1)) == []


def test_upcoming_includes_today_boundary(isolated_home, fixture_list_text: str) -> None:
    """窗口右边界含当天：9/21 + 1 天 = 9/22，应含 9/21 与 9/22 的条目。"""
    items = upcoming(1, session=_list_session(fixture_list_text), today=date(2026, 9, 21))
    assert {i.date_only for i in items} == {date(2026, 9, 21), date(2026, 9, 22)}


def test_upcoming_negative_days_raises() -> None:
    with pytest.raises(ValueError):
        upcoming(-1)