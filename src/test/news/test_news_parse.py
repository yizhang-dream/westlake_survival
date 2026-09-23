"""``westlake_survival.news`` 的离线解析与查询测试。

全部离线：fixture 是真实页面片段，网络层用
:class:`news_fakes.FakeSession` 或 monkeypatch 打桩。
"""

from __future__ import annotations

from datetime import datetime

import pytest
import requests

from news_fakes import FakeResponse, FakeSession
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError
from westlake_survival.news import (
    CATEGORIES,
    DETAIL_COMPONENT,
    LIST_COMPONENT,
    NEWS_URL,
    NewsDetail,
    NewsItem,
    fetch_detail,
    latest,
    parse_datetime,
    parse_news_detail,
    parse_news_list,
)


# --------------------------------------------------------------------------- #
# 日期解析
# --------------------------------------------------------------------------- #
def test_parse_datetime_full() -> None:
    assert parse_datetime("2026-09-22 11:24:35") == datetime(2026, 9, 22, 11, 24, 35)


def test_parse_datetime_date_only_and_slash() -> None:
    assert parse_datetime("2026-09-22") == datetime(2026, 9, 22, 0, 0, 0)
    assert parse_datetime("2026/09/22 08:05") == datetime(2026, 9, 22, 8, 5, 0)


def test_parse_datetime_invalid_returns_none() -> None:
    assert parse_datetime("") is None
    assert parse_datetime("not a date") is None
    assert parse_datetime("2026-13-40") is None


# --------------------------------------------------------------------------- #
# 列表页解析
# --------------------------------------------------------------------------- #
def test_parse_list_returns_items(list_html: str) -> None:
    items = parse_news_list(list_html)

    assert len(items) == 4
    assert all(isinstance(item, NewsItem) for item in items)


def test_field_mapping_title_is_content_category_is_title(list_html: str) -> None:
    """核心陷阱：原始 title 是**分类**、content 才是**标题**。"""
    first = parse_news_list(list_html)[0]

    assert first.category == "人物"  # 来自原始 title
    assert first.title == "本校“最大气”的两位老师！"  # 来自原始 content
    assert first.category != first.title
    # 反向确认：raw 里两个字段的语义与映射相反
    assert first.raw["title"] == first.category
    assert first.raw["content"] == first.title


def test_parse_list_other_fields(list_html: str) -> None:
    first = parse_news_list(list_html)[0]

    assert first.date == datetime(2026, 9, 22, 11, 24, 35)
    assert first.url.endswith("/people/202609/t20260922_69940.html")
    assert first.img_url.endswith("W020260922412722347323.jpg")


def test_parse_list_handles_function_callback(list_html: str) -> None:
    """组件块含 ``turnToEn: function () {}``，不能整块 js_literal。"""
    assert "function" in list_html
    assert len(parse_news_list(list_html)) == 4


def test_parse_list_repairs_mojibake(list_mojibake: str) -> None:
    """latin-1 乱码文本应被修复回中文（无 charset 头的坑）。"""
    assert "人物" not in list_mojibake
    items = parse_news_list(list_mojibake)
    assert items[0].category == "人物"
    assert items[0].title.startswith("本校")


def test_parse_list_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_news_list("<html><body>nothing here</body></html>")


def test_parse_list_missing_array_raises() -> None:
    html = '<script>new allNews("#app", { page: 1, });</script>'
    with pytest.raises(ParseError):
        parse_news_list(html)


# --------------------------------------------------------------------------- #
# 详情页解析
# --------------------------------------------------------------------------- #
def test_parse_detail_fields(detail_html: str) -> None:
    detail = parse_news_detail(detail_html, url="https://x/t1.html")

    assert isinstance(detail, NewsDetail)
    assert detail.title == "本校“最大气”的两位老师！"
    assert detail.category == "人物"
    assert detail.author == ""
    assert detail.date == datetime(2026, 9, 22, 11, 24, 35)
    assert detail.url == "https://x/t1.html"
    assert "大气层消失" in detail.content_html


def test_parse_detail_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_news_detail("<html></html>")


def test_parse_detail_missing_main_obj_raises() -> None:
    html = '<script>new newsDetail("#app", { other: 1 });</script>'
    with pytest.raises(ParseError):
        parse_news_detail(html)


# --------------------------------------------------------------------------- #
# latest：过滤 / 截断 / 网络
# --------------------------------------------------------------------------- #
@pytest.fixture
def stub_list(monkeypatch, list_html: str):
    """把列表页抓取打桩成返回真实 fixture 文本，记录调用。"""
    calls: list[dict] = []

    def fake(url, *, cache_name=None, session=None, timeout=None):
        calls.append({"url": url, "cache_name": cache_name, "timeout": timeout})
        return list_html, None

    monkeypatch.setattr("westlake_survival.news.http_get_with_etag", fake)
    return calls


def test_latest_all(stub_list) -> None:
    items = latest()

    assert len(items) == 4
    assert stub_list[0]["url"] == NEWS_URL
    assert stub_list[0]["timeout"] > 0


def test_latest_filter_by_category(stub_list) -> None:
    people = latest(category="人物")
    news = latest(category="资讯")

    assert [i.category for i in people] == ["人物", "人物"]
    assert [i.category for i in news] == ["资讯", "资讯"]
    assert [i.title for i in people] == [
        "本校“最大气”的两位老师！",
        "两位国际天文奥赛金牌少年，在西湖撞了个满怀",
    ]


def test_latest_filter_unknown_category_is_empty(stub_list) -> None:
    assert latest(category="不存在") == []


def test_latest_limit(stub_list) -> None:
    assert len(latest(limit=2)) == 2
    assert latest(limit=0) == []
    assert len(latest(category="人物", limit=1)) == 1


def test_latest_categories_constant() -> None:
    assert "人物" in CATEGORIES and "资讯" in CATEGORIES


def test_latest_decodes_utf8_not_latin1(monkeypatch, list_html: str) -> None:
    """列表页响应无 charset，必须走 UTF-8 路径。"""
    session = FakeSession(lambda url, kw: FakeResponse(list_html, url=url))
    items = latest(session=session)

    assert items[0].title.startswith("本校")


def test_latest_timeout_maps_to_westlake_error(monkeypatch) -> None:
    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("westlake_survival.news.http_get_with_etag", boom)
    with pytest.raises(WestlakeError) as excinfo:
        latest()
    assert "超时" in str(excinfo.value)


def test_latest_connection_error_maps_to_westlake_error(monkeypatch) -> None:
    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr("westlake_survival.news.http_get_with_etag", boom)
    with pytest.raises(WestlakeError) as excinfo:
        latest()
    assert "失败" in str(excinfo.value)


def test_latest_http_500_maps_to_parse_error(monkeypatch) -> None:
    response = FakeResponse(b"boom", status=500, url=NEWS_URL)
    error = requests.HTTPError("500")
    error.response = response

    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise error

    monkeypatch.setattr("westlake_survival.news.http_get_with_etag", boom)
    with pytest.raises(ParseError):
        latest()


def test_latest_403_offcampus(monkeypatch) -> None:
    body = b"Access forbidden, please contact administrator"
    response = FakeResponse(body, status=403, url=NEWS_URL)
    error = requests.HTTPError("403")
    error.response = response

    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise error

    monkeypatch.setattr("westlake_survival.news.http_get_with_etag", boom)
    with pytest.raises(OffCampusError):
        latest()


def test_latest_parse_failure_when_page_changed(monkeypatch) -> None:
    def fake(url, *, cache_name=None, session=None, timeout=None):
        return "<html>改版了</html>", None

    monkeypatch.setattr("westlake_survival.news.http_get_with_etag", fake)
    with pytest.raises(ParseError):
        latest()


# --------------------------------------------------------------------------- #
# fetch_detail：网络
# --------------------------------------------------------------------------- #
def test_fetch_detail_ok(detail_html: str) -> None:
    url = "https://www.westlake.edu.cn/news_events/westlakenews/people/202609/t20260922_69940.html"
    session = FakeSession(lambda u, kw: FakeResponse(detail_html, url=u))

    detail = fetch_detail(url, session=session)

    assert detail.title == "本校“最大气”的两位老师！"
    assert session.calls[0][0] == url
    assert session.calls[0][1]["timeout"] > 0


def test_fetch_detail_decodes_utf8_not_latin1(detail_html: str) -> None:
    """详情页同样无 charset；FakeResponse.text 是乱码，必须走 content。"""
    session = FakeSession(lambda u, kw: FakeResponse(detail_html, url=u))

    detail = fetch_detail("https://x/d.html", session=session)

    assert detail.title == "本校“最大气”的两位老师！"
    assert detail.category == "人物"


def test_fetch_detail_empty_url_raises() -> None:
    with pytest.raises(ValueError):
        fetch_detail("")


def test_fetch_detail_timeout_maps_to_westlake_error() -> None:
    def boom(url, kw):
        raise requests.Timeout("timed out")

    with pytest.raises(WestlakeError) as excinfo:
        fetch_detail("https://x/d.html", session=FakeSession(boom))
    assert "超时" in str(excinfo.value)


def test_fetch_detail_connection_error_maps_to_westlake_error() -> None:
    def boom(url, kw):
        raise requests.ConnectionError("no route")

    with pytest.raises(WestlakeError) as excinfo:
        fetch_detail("https://x/d.html", session=FakeSession(boom))
    assert "失败" in str(excinfo.value)


def test_fetch_detail_http_404_maps_to_parse_error() -> None:
    session = FakeSession(lambda u, kw: FakeResponse(b"nope", status=404, url=u))
    with pytest.raises(ParseError):
        fetch_detail("https://x/d.html", session=session)


def test_fetch_detail_403_offcampus() -> None:
    body = b"Access forbidden, please contact administrator"
    session = FakeSession(lambda u, kw: FakeResponse(body, status=403, url=u))
    with pytest.raises(OffCampusError):
        fetch_detail("https://x/d.html", session=session)


def test_fetch_detail_parse_failure() -> None:
    session = FakeSession(lambda u, kw: FakeResponse(b"<html></html>", url=u))
    with pytest.raises(ParseError):
        fetch_detail("https://x/d.html", session=session)


def test_component_names_are_real() -> None:
    assert LIST_COMPONENT == "allNews"
    assert DETAIL_COMPONENT == "newsDetail"