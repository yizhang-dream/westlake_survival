"""``westlake_survival.research`` 的离线解析与查询测试。

全部离线：fixture 是真实页面片段，网络层用
:class:`research_fakes.FakeSession` 或 monkeypatch 打桩。
"""

from __future__ import annotations

from datetime import datetime

import pytest
import requests

from research_fakes import FakeResponse, FakeSession
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError
from westlake_survival.research import (
    CACHE_NAME,
    CATEGORIES,
    DETAIL_COMPONENT,
    LIST_COMPONENT,
    RESEARCH_URL,
    ResearchDetail,
    ResearchItem,
    fetch_detail,
    latest,
    parse_research_detail,
    parse_research_list,
    parse_url_date,
)


# --------------------------------------------------------------------------- #
# URL 日期推断
# --------------------------------------------------------------------------- #
def test_parse_url_date_from_t_yyyymmdd() -> None:
    url = "https://x/good_health_wellbeing/202510/t20251016_60343.html"
    assert parse_url_date(url) == datetime(2025, 10, 16)


def test_parse_url_date_shtml_and_elsewhere_in_path() -> None:
    assert parse_url_date(
        "https://www.westlake.edu.cn/news_events/westlakenews/Research/202511/t20251114_61277.html"
    ) == datetime(2025, 11, 14)
    assert parse_url_date("https://medicine.westlake.edu.cn/News/202408/t20240802_41882.shtml") == (
        datetime(2024, 8, 2)
    )


def test_parse_url_date_no_fragment_or_invalid_is_none() -> None:
    assert parse_url_date("") is None
    assert parse_url_date("https://x/plain/page.html") is None
    assert parse_url_date("https://x/t20261340_1.html") is None  # 月份 13 非法
    assert parse_url_date("https://x/t20250230_1.html") is None  # 2 月 30 日非法


# --------------------------------------------------------------------------- #
# 列表页解析
# --------------------------------------------------------------------------- #
def test_parse_list_returns_items(list_html: str) -> None:
    items = parse_research_list(list_html)

    assert len(items) == 5
    assert all(isinstance(item, ResearchItem) for item in items)


def test_parse_list_maps_abs_to_title_and_summary(list_html: str) -> None:
    """条目文本只有 ``abs``，同时映射为 title 与 summary。"""
    first = parse_research_list(list_html)[0]

    assert first.title == "西湖大学卢培龙研究团队及其合作者从头设计新型电压门控阴离子通道"
    assert first.summary == first.title
    assert first.raw["abs"] == first.title
    assert first.category == "生命健康 / Good Health & Wellbeing"


def test_parse_list_category_is_group_title(list_html: str) -> None:
    items = parse_research_list(list_html)

    assert [i.category for i in items] == [
        "生命健康 / Good Health & Wellbeing",
        "生命健康 / Good Health & Wellbeing",
        "生命健康 / Good Health & Wellbeing",
        "医学创新 / Treatment & Cures for Diseases",
        "医学创新 / Treatment & Cures for Diseases",
    ]
    # 分组名是方向，不是条目标题
    assert all(item.category != item.title for item in items)


def test_parse_list_other_fields(list_html: str) -> None:
    first = parse_research_list(list_html)[0]

    assert first.date == datetime(2025, 10, 16)
    assert first.url.endswith("/good_health_wellbeing/202510/t20251016_60343.html")
    assert first.img_url.endswith("W020251016821762002388.jpg")


def test_parse_list_handles_function_callback(list_html: str) -> None:
    """组件块含 ``mounted: function () { }``，不能整块 js_literal。"""
    assert "function" in list_html
    assert len(parse_research_list(list_html)) == 5


def test_parse_list_repairs_mojibake(list_mojibake: str) -> None:
    """latin-1 乱码文本应被修复回中文（无 charset 头的坑）。"""
    assert "生命健康" not in list_mojibake
    items = parse_research_list(list_mojibake)
    assert items[0].category == "生命健康 / Good Health & Wellbeing"
    assert items[0].title.startswith("西湖大学卢培龙")


def test_parse_list_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_research_list("<html><body>nothing here</body></html>")


def test_parse_list_missing_array_raises() -> None:
    html = '<script>new researchWestlake("#app", { mainObj: { brief: "x" } });</script>'
    with pytest.raises(ParseError):
        parse_research_list(html)


def test_parse_list_skips_groups_without_list() -> None:
    html = (
        '<script>new researchWestlake("#app", { researchList: ['
        '{ title: "空组" }, { title: "有组", list: [{ url: "https://x/t20250101_1.html", abs: "内容" }] }'
        "] });</script>"
    )
    items = parse_research_list(html)

    assert len(items) == 1
    assert items[0].category == "有组"
    assert items[0].date == datetime(2025, 1, 1)


# --------------------------------------------------------------------------- #
# 详情页解析
# --------------------------------------------------------------------------- #
def test_parse_detail_fields(detail_html: str) -> None:
    detail = parse_research_detail(detail_html, url="https://x/t20251016_60343.html")

    assert isinstance(detail, ResearchDetail)
    assert detail.title == "西湖大学卢培龙研究团队及其合作者从头设计新型电压门控阴离子通道"
    assert detail.category == "学术"
    assert detail.author == ""
    assert detail.date == datetime(2025, 10, 16, 21, 59, 19)
    assert detail.url == "https://x/t20251016_60343.html"
    assert "离子通道" in detail.content_html


def test_parse_detail_date_falls_back_to_url(detail_html: str) -> None:
    """详情页 ``Data`` 缺失时用 URL 的 tYYYYMMDD 兜底。"""
    html = detail_html.replace('Data:  "2025-10-16 21:59:19"', 'Data:  ""')
    detail = parse_research_detail(html, url="https://x/good_health_wellbeing/202510/t20251016_60343.html")

    assert detail.date == datetime(2025, 10, 16)


def test_parse_detail_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_research_detail("<html></html>")


def test_parse_detail_missing_main_obj_raises() -> None:
    html = '<script>new newsDetail("#app", { other: 1 });</script>'
    with pytest.raises(ParseError):
        parse_research_detail(html)


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

    monkeypatch.setattr("westlake_survival.research.http_get_with_etag", fake)
    return calls


def test_latest_all(stub_list) -> None:
    items = latest()

    assert len(items) == 5
    assert stub_list[0]["url"] == RESEARCH_URL
    assert stub_list[0]["cache_name"] == CACHE_NAME
    assert stub_list[0]["timeout"] > 0


def test_latest_filter_by_category(stub_list) -> None:
    health = latest(category="生命健康 / Good Health & Wellbeing")
    medicine = latest(category="医学创新 / Treatment & Cures for Diseases")

    assert len(health) == 3
    assert len(medicine) == 2
    assert all(i.category == "生命健康 / Good Health & Wellbeing" for i in health)
    assert medicine[0].title == "免疫细胞“王牌情报员”cDC1的突围之战 | Science报道"


def test_latest_filter_unknown_category_is_empty(stub_list) -> None:
    assert latest(category="不存在") == []


def test_latest_limit(stub_list) -> None:
    assert len(latest(limit=2)) == 2
    assert latest(limit=0) == []
    assert len(latest(category="医学创新 / Treatment & Cures for Diseases", limit=1)) == 1


def test_latest_decodes_utf8_not_latin1(list_html: str) -> None:
    """列表页响应无 charset，必须走 UTF-8 路径。"""
    session = FakeSession(lambda url, kw: FakeResponse(list_html, url=url))
    items = latest(session=session)

    assert items[0].title.startswith("西湖大学卢培龙")


def test_latest_timeout_maps_to_westlake_error(monkeypatch) -> None:
    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("westlake_survival.research.http_get_with_etag", boom)
    with pytest.raises(WestlakeError) as excinfo:
        latest()
    assert "超时" in str(excinfo.value)


def test_latest_connection_error_maps_to_westlake_error(monkeypatch) -> None:
    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr("westlake_survival.research.http_get_with_etag", boom)
    with pytest.raises(WestlakeError) as excinfo:
        latest()
    assert "失败" in str(excinfo.value)


def test_latest_http_500_maps_to_parse_error(monkeypatch) -> None:
    response = FakeResponse(b"boom", status=500, url=RESEARCH_URL)
    error = requests.HTTPError("500")
    error.response = response

    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise error

    monkeypatch.setattr("westlake_survival.research.http_get_with_etag", boom)
    with pytest.raises(ParseError):
        latest()


def test_latest_403_offcampus(monkeypatch) -> None:
    body = b"Access forbidden, please contact administrator"
    response = FakeResponse(body, status=403, url=RESEARCH_URL)
    error = requests.HTTPError("403")
    error.response = response

    def boom(url, *, cache_name=None, session=None, timeout=None):
        raise error

    monkeypatch.setattr("westlake_survival.research.http_get_with_etag", boom)
    with pytest.raises(OffCampusError):
        latest()


def test_latest_parse_failure_when_page_changed(monkeypatch) -> None:
    def fake(url, *, cache_name=None, session=None, timeout=None):
        return "<html>改版了</html>", None

    monkeypatch.setattr("westlake_survival.research.http_get_with_etag", fake)
    with pytest.raises(ParseError):
        latest()


# --------------------------------------------------------------------------- #
# fetch_detail：网络
# --------------------------------------------------------------------------- #
def test_fetch_detail_ok(detail_html: str) -> None:
    url = "https://www.westlake.edu.cn/research/research_at_westlake/good_health_wellbeing/202510/t20251016_60343.html"
    session = FakeSession(lambda u, kw: FakeResponse(detail_html, url=u))

    detail = fetch_detail(url, session=session)

    assert detail.title.startswith("西湖大学卢培龙")
    assert session.calls[0][0] == url
    assert session.calls[0][1]["timeout"] > 0


def test_fetch_detail_decodes_utf8_not_latin1(detail_html: str) -> None:
    """详情页同样无 charset；FakeResponse.text 是乱码，必须走 content。"""
    session = FakeSession(lambda u, kw: FakeResponse(detail_html, url=u))

    detail = fetch_detail("https://x/t20251016_1.html", session=session)

    assert detail.category == "学术"
    assert "离子通道" in detail.content_html


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


def test_component_names_and_categories_are_real() -> None:
    assert LIST_COMPONENT == "researchWestlake"
    assert DETAIL_COMPONENT == "newsDetail"
    assert "生命健康 / Good Health & Wellbeing" in CATEGORIES
    assert len(CATEGORIES) == 7
