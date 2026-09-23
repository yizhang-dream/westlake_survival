"""``westlake_survival.search`` 的离线解析与查询测试。

全部离线：fixture 是真实响应体（保留前导空行），网络层用
:class:`search_fakes.FakeSession` 打桩。
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from search_fakes import FakeResponse, FakeSession
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError
from westlake_survival.search import (
    CHANNEL_ID,
    SEARCH_URL,
    SearchHit,
    SearchResult,
    parse_date,
    parse_search,
    search,
    strip_font_tags,
)


# --------------------------------------------------------------------------- #
# 文本清洗与日期
# --------------------------------------------------------------------------- #
def test_strip_font_tags_removes_highlight() -> None:
    assert strip_font_tags("<font color=>西湖</font>理学讲坛") == "西湖理学讲坛"


def test_strip_font_tags_handles_nested_and_attrs() -> None:
    assert (
        strip_font_tags('<font color="red">西湖</font>大学<FONT size=2>官网</FONT>')
        == "西湖大学官网"
    )


def test_strip_font_tags_empty() -> None:
    assert strip_font_tags("") == ""
    assert strip_font_tags("  普通标题  ") == "普通标题"


def test_parse_date_iso_and_slash() -> None:
    assert parse_date("2026-09-23") == date(2026, 9, 23)
    assert parse_date("2026/09/23") == date(2026, 9, 23)
    assert parse_date("") is None
    assert parse_date("2026-13-40") is None


# --------------------------------------------------------------------------- #
# 解析真实响应 fixture
# --------------------------------------------------------------------------- #
def _payload(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8").strip())


def test_parse_page1_envelope(raw_page1: bytes) -> None:
    result = parse_search(_payload(raw_page1))

    assert isinstance(result, SearchResult)
    assert result.page == 1
    assert result.page_count == 392
    assert result.total == 3916
    assert len(result.hits) == 3
    assert result.has_next is True
    assert [h.clean_title for h in result] == [h.clean_title for h in result.hits]


def test_parse_page1_first_hit_fields(raw_page1: bytes) -> None:
    hit = parse_search(_payload(raw_page1)).hits[0]

    assert isinstance(hit, SearchHit)
    assert hit.title == "<font color=>西湖</font>理学讲坛| 程金光：稀土Eu掺杂无限层镍基超导薄膜的反常物性研究"
    assert hit.clean_title == "西湖理学讲坛| 程金光：稀土Eu掺杂无限层镍基超导薄膜的反常物性研究"
    assert hit.date == date(2026, 9, 23)
    assert hit.url.endswith("/202609/t20260916_69819.html")
    assert hit.docchannel == 4721
    assert hit.author == ""
    assert "<font" not in hit.clean_desc
    assert hit.raw["docid"] == 69819


def test_parse_page2_matches_fixture(raw_page2: bytes) -> None:
    result = parse_search(_payload(raw_page2))

    assert result.page == 2
    assert result.page_count == 392
    assert result.total == 3916
    assert len(result.hits) == 3
    assert result.hits[0].clean_title == "两位国际天文奥赛金牌少年，在西湖撞了个满怀"
    assert result.hits[0].date == date(2026, 9, 17)


def test_parse_preserves_author_as_is() -> None:
    """``author`` 在招聘类条目里是分类词（如「全职」）而非人名，原样保留。"""
    result = parse_search({"data": [{"title": "招聘启事", "url": "u", "author": "全职"}]})
    assert result.hits[0].author == "全职"


# --------------------------------------------------------------------------- #
# 解析边界
# --------------------------------------------------------------------------- #
def test_parse_empty_hits() -> None:
    result = parse_search({"page": 5, "pageCount": 0, "count": 0, "data": []})
    assert result.hits == []
    assert result.total == 0
    assert result.page == 5
    assert result.has_next is False


def test_parse_missing_data_key_is_empty() -> None:
    result = parse_search({"page": 1, "count": 0})
    assert result.hits == []
    assert result.total == 0


def test_parse_data_not_list_raises() -> None:
    with pytest.raises(ParseError):
        parse_search({"data": "oops"})


def test_parse_skips_non_dict_items() -> None:
    result = parse_search({"data": ["x", {"title": "ok", "url": "u"}], "count": 1})
    assert len(result.hits) == 1
    assert result.hits[0].clean_title == "ok"


def test_parse_hit_with_bad_date() -> None:
    result = parse_search({"data": [{"title": "t", "url": "u", "time": ""}]})
    assert result.hits[0].date is None


def test_search_result_helpers() -> None:
    hit = SearchHit(title="<font color=>x</font>", url="u")
    result = SearchResult(hits=[hit], page=1, page_count=1, total=1)
    assert len(result) == 1
    assert list(result) == [hit]
    assert result.has_next is False
    assert hit.clean_title == "x"


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def test_search_decodes_bytes_not_latin1(raw_page1: bytes) -> None:
    """响应头是 text/html，必须走 content 字节路径（否则中文乱码）。"""
    session = FakeSession(lambda url, kw: FakeResponse(raw_page1, url=url))
    result = search("西湖", session=session)

    assert result.total == 3916
    assert result.hits[0].clean_title.startswith("西湖理学讲坛")


def test_search_builds_request_params(raw_page1: bytes) -> None:
    session = FakeSession(lambda url, kw: FakeResponse(raw_page1, url=url))
    search("西湖", page=2, session=session)

    url, kwargs = session.calls[0]
    assert url == SEARCH_URL
    assert kwargs["params"] == {"channelid": CHANNEL_ID, "searchword": "西湖", "page": 2}
    assert kwargs["timeout"] > 0


def test_search_page_must_be_positive() -> None:
    with pytest.raises(ValueError):
        search("西湖", page=0)


def test_search_empty_body_raises_parse_error() -> None:
    session = FakeSession(lambda url, kw: FakeResponse(b"", url=url))
    with pytest.raises(ParseError):
        search("西湖", session=session)


def test_search_html_body_raises_parse_error() -> None:
    """接口偶发返回 HTML（如维护页）时应抛 ParseError 而非 JSONDecodeError。"""
    session = FakeSession(lambda url, kw: FakeResponse(b"<html>maintenance</html>", url=url))
    with pytest.raises(ParseError):
        search("西湖", session=session)


def test_search_http_500_raises_parse_error() -> None:
    session = FakeSession(lambda url, kw: FakeResponse(b"boom", status=500, url=url))
    with pytest.raises(ParseError):
        search("西湖", session=session)


def test_search_403_offcampus_marker() -> None:
    body = b"Access forbidden, please contact administrator"
    session = FakeSession(lambda url, kw: FakeResponse(body, status=403, url=url))
    with pytest.raises(OffCampusError):
        search("西湖", session=session)


def test_search_timeout_maps_to_westlake_error() -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.Timeout("timed out")

    with pytest.raises(WestlakeError) as excinfo:
        search("西湖", session=FakeSession(boom))
    assert "超时" in str(excinfo.value)


def test_search_connection_error_maps_to_westlake_error() -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.ConnectionError("no route to host")

    with pytest.raises(WestlakeError) as excinfo:
        search("西湖", session=FakeSession(boom))
    assert "失败" in str(excinfo.value)