"""``westlake_survival.careers`` 的离线解析与查询测试。

全部离线：fixture 是真实页面片段（保留 ``new career(...)`` 外壳与真实
``type`` 字段格式），网络层用 :class:`careers_fakes.FakeSession` 打桩。
"""

from __future__ import annotations

from datetime import date

import pytest

from careers_fakes import FakeCache, FakeResponse, FakeSession
from westlake_survival import careers
from westlake_survival.careers import (
    COMPONENT_NAME,
    DETAIL_COMPONENT_NAME,
    POSITIONS_URL,
    Position,
    PositionDetail,
    fetch_detail,
    is_external_url,
    parse_date,
    parse_detail,
    parse_position,
    parse_positions,
    positions,
    split_type,
)
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError


# --------------------------------------------------------------------------- #
# type 字段拆分
# --------------------------------------------------------------------------- #
def test_split_type_three_parts() -> None:
    assert split_type("全职, 生命科学学院, 中国杭州，云谷校区") == (
        "全职",
        "生命科学学院",
        "中国杭州，云谷校区",
    )


def test_split_type_keeps_chinese_comma_inside_location() -> None:
    """地点段含中文逗号，必须只切两刀，不能被切碎。"""
    job_type, dept, loc = split_type("全职, 医学院, 中国杭州，云谷校区")
    assert loc == "中国杭州，云谷校区"
    assert "，" in loc
    assert (job_type, dept) == ("全职", "医学院")


def test_split_type_handles_ascii_only_separators() -> None:
    assert split_type("全职, 工学院, 中国杭州") == ("全职", "工学院", "中国杭州")


def test_split_type_empty_department() -> None:
    assert split_type("全职, , 中国杭州，云栖校区") == ("全职", "", "中国杭州，云栖校区")


def test_split_type_short_and_empty() -> None:
    assert split_type("") == ("", "", "")
    assert split_type("全职") == ("全职", "", "")


# --------------------------------------------------------------------------- #
# 日期
# --------------------------------------------------------------------------- #
def test_parse_date_iso_and_slash() -> None:
    assert parse_date("2026-09-20") == date(2026, 9, 20)
    assert parse_date("2026/09/20") == date(2026, 9, 20)


def test_parse_date_invalid() -> None:
    assert parse_date("") is None
    assert parse_date("2026-13-40") is None


# --------------------------------------------------------------------------- #
# 解析 fixture
# --------------------------------------------------------------------------- #
def test_parse_positions_returns_all_fixture_rows(fixture_positions_html: str) -> None:
    items = parse_positions(fixture_positions_html)

    assert len(items) == 6
    assert all(isinstance(p, Position) for p in items)


def test_parse_positions_first_row_fields(fixture_positions_html: str) -> None:
    first = parse_positions(fixture_positions_html)[0]

    assert first.title == "西湖大学生命科学学院贾洁敏课题组博士后招聘启事"
    assert first.category == "博士后"
    assert first.job_type == "全职"
    assert first.department == "生命科学学院"
    assert first.location == "中国杭州，云谷校区"
    assert first.date == date(2026, 9, 20)
    assert first.url.endswith("/202508/t20250827_58219.html")
    assert first.external_url == ""
    assert first.raw["target"] == "_self"


def test_parse_position_apply_url_falls_back_to_official_url() -> None:
    pos = parse_position(
        {
            "category": "科研团队",
            "dept": "某实验室招聘",
            "type": "全职, 工学院, 中国杭州",
            "url": "https://www.westlake.edu.cn/a.html",
            "url2": "",
            "date": "2026-09-01",
        }
    )
    assert pos.apply_url == "https://www.westlake.edu.cn/a.html"
    assert pos.is_external is False


def test_parse_position_apply_url_prefers_external_url() -> None:
    """``url2`` 非空时申请链接必须优先给外部平台链接。"""
    pos = parse_position(
        {
            "category": "行政服务",
            "dept": "某行政岗",
            "type": "全职, 人力资源部, 中国杭州",
            "url": "https://www.westlake.edu.cn/a.html",
            "url2": "https://app.mokahr.com/social-recruitment/westlake/43525#/jobs/1",
            "date": "2026-09-02",
        }
    )
    assert pos.apply_url == "https://app.mokahr.com/social-recruitment/westlake/43525#/jobs/1"
    assert pos.external_url == pos.apply_url
    assert pos.is_external is True


def test_parse_positions_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_positions("<html><body>no component here</body></html>")


def test_parse_positions_missing_role_list_raises() -> None:
    html = '<script>new career("#app", { pageSize: 15, mounted: function () { } });</script>'
    with pytest.raises(ParseError):
        parse_positions(html)


def test_component_name_is_career() -> None:
    assert COMPONENT_NAME == "career"


# --------------------------------------------------------------------------- #
# 详情解析
# --------------------------------------------------------------------------- #
def test_parse_detail_fields(fixture_detail_html: str) -> None:
    detail = parse_detail(fixture_detail_html, "https://www.westlake.edu.cn/x.html")

    assert isinstance(detail, PositionDetail)
    assert detail.title == "西湖大学生命科学学院贾洁敏课题组博士后招聘启事"
    assert detail.category == "博士后"
    assert detail.department == "生命科学学院"
    assert detail.address == "中国杭州，云谷校区"
    assert detail.job_type == "全职"
    assert detail.url == "https://www.westlake.edu.cn/x.html"
    assert "课题组简介" in detail.content_html
    assert detail.content_html.lstrip().startswith("<div")


def test_detail_component_name() -> None:
    assert DETAIL_COMPONENT_NAME == "careerDetail"


def test_parse_detail_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_detail("<html></html>")


# --------------------------------------------------------------------------- #
# 过滤
# --------------------------------------------------------------------------- #
def _session(html: str) -> FakeSession:
    return FakeSession(lambda url, kw: FakeResponse(html, url=url))


def test_positions_category_filter(fixture_positions_html: str) -> None:
    items = positions(category="博士后", session=_session(fixture_positions_html))

    assert len(items) == 3
    assert {p.category for p in items} == {"博士后"}


def test_positions_keyword_filter_case_insensitive(fixture_positions_html: str) -> None:
    items = positions(keyword="许田", session=_session(fixture_positions_html))
    assert len(items) == 1
    assert "许田" in items[0].title

    # 英文标题的大小写不敏感匹配
    html = (
        '<script>new career("#app", { roleList: ['
        '{category: "博士后", dept: "Postdoctoral position in TORRES Lab",'
        ' type: "全职, , 中国杭州", url: "u", url2: "", date: "2026-01-01"},'
        '] });</script>'
    )
    assert len(positions(keyword="torres", session=_session(html))) == 1
    assert len(positions(keyword="TORRES", session=_session(html))) == 1


def test_positions_limit(fixture_positions_html: str) -> None:
    items = positions(limit=2, session=_session(fixture_positions_html))
    assert len(items) == 2


def test_positions_category_and_keyword_combined(fixture_positions_html: str) -> None:
    items = positions(
        category="科研团队", keyword="可信及通用", session=_session(fixture_positions_html)
    )
    assert len(items) == 1
    assert "可信及通用人工智能实验室" in items[0].title
    # 同一关键词换类别后应被类别过滤掉
    other = positions(
        category="博士后", keyword="可信及通用", session=_session(fixture_positions_html)
    )
    assert other == []


def test_positions_no_match_returns_empty(fixture_positions_html: str) -> None:
    assert positions(keyword="不存在的岗位", session=_session(fixture_positions_html)) == []


def test_positions_negative_limit_raises() -> None:
    with pytest.raises(ValueError):
        positions(limit=-1)


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def test_positions_decodes_bytes_not_latin1(fixture_positions_bytes: bytes) -> None:
    """响应无 charset 头，必须走 content 字节路径（否则中文乱码）。"""
    session = FakeSession(lambda url, kw: FakeResponse(fixture_positions_bytes, url=url))
    items = positions(session=session)

    assert items[0].title == "西湖大学生命科学学院贾洁敏课题组博士后招聘启事"


def test_positions_uses_list_url(fixture_positions_bytes: bytes) -> None:
    session = FakeSession(lambda url, kw: FakeResponse(fixture_positions_bytes, url=url))
    positions(session=session)

    url, kwargs = session.calls[0]
    assert url == POSITIONS_URL
    assert kwargs["timeout"] > 0


def test_positions_http_500_raises_parse_error() -> None:
    session = FakeSession(lambda url, kw: FakeResponse(b"boom", status=500, url=url))
    with pytest.raises(ParseError):
        positions(session=session)


def test_positions_403_offcampus_marker() -> None:
    body = b"Access forbidden, please contact administrator"
    session = FakeSession(lambda url, kw: FakeResponse(body, status=403, url=url))
    with pytest.raises(OffCampusError):
        positions(session=session)


def test_positions_timeout_maps_to_westlake_error() -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.Timeout("timed out")

    with pytest.raises(WestlakeError) as excinfo:
        positions(session=FakeSession(boom))
    assert "超时" in str(excinfo.value)


def test_positions_connection_error_maps_to_westlake_error() -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.ConnectionError("no route to host")

    with pytest.raises(WestlakeError) as excinfo:
        positions(session=FakeSession(boom))
    assert "失败" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# ETag 条件 GET
# --------------------------------------------------------------------------- #
def test_positions_sends_if_none_match_when_cached(
    monkeypatch, fixture_positions_bytes: bytes
) -> None:
    cache = FakeCache(etag='"abc"', body=fixture_positions_bytes.decode("utf-8"))
    monkeypatch.setattr(careers._cache, "load_json", cache.load_json)
    monkeypatch.setattr(careers._cache, "save_json", cache.save_json)

    session = FakeSession(
        lambda url, kw: FakeResponse(fixture_positions_bytes, status=304, url=url)
    )
    items = positions(session=session)

    assert len(items) == 6
    assert session.calls[0][1]["headers"] == {"If-None-Match": '"abc"'}


def test_positions_saves_etag_when_server_provides(
    monkeypatch, fixture_positions_bytes: bytes
) -> None:
    cache = FakeCache()
    monkeypatch.setattr(careers._cache, "load_json", cache.load_json)
    monkeypatch.setattr(careers._cache, "save_json", cache.save_json)

    session = FakeSession(
        lambda url, kw: FakeResponse(
            fixture_positions_bytes, url=url, headers={"ETag": '"xyz"'}
        )
    )
    positions(session=session)

    assert cache.store[careers.CACHE_NAME]["etag"] == '"xyz"'
    assert "roleList" in cache.store[careers.CACHE_NAME]["body"]


# --------------------------------------------------------------------------- #
# fetch_detail
# --------------------------------------------------------------------------- #
def test_fetch_detail_parses_official_page(fixture_detail_html: str) -> None:
    session = FakeSession(lambda url, kw: FakeResponse(fixture_detail_html, url=url))
    detail = fetch_detail("https://www.westlake.edu.cn/x.html", session=session)

    assert detail.title == "西湖大学生命科学学院贾洁敏课题组博士后招聘启事"
    assert session.calls[0][0] == "https://www.westlake.edu.cn/x.html"


def test_fetch_detail_external_url_short_circuits() -> None:
    """外部招聘平台链接不做请求、不做解析，直接返回外链。"""
    session = FakeSession(lambda url, kw: FakeResponse(b"should not be fetched", url=url))
    url = "https://app.mokahr.com/social-recruitment/westlake/43525#/jobs/1"
    detail = fetch_detail(url, session=session)

    assert detail.url == url
    assert detail.content_html == ""
    assert detail.title == ""
    assert session.calls == []


def test_is_external_url() -> None:
    assert is_external_url("https://app.mokahr.com/x") is True
    assert is_external_url("https://www.westlake.edu.cn/careers/x.html") is False
    assert is_external_url("") is False


def test_fetch_detail_empty_url_raises() -> None:
    with pytest.raises(ValueError):
        fetch_detail("   ")


def test_fetch_detail_http_error(fixture_detail_html: str) -> None:
    session = FakeSession(lambda url, kw: FakeResponse(b"nope", status=404, url=url))
    with pytest.raises(ParseError):
        fetch_detail("https://www.westlake.edu.cn/x.html", session=session)


def test_fetch_detail_timeout_maps_to_westlake_error() -> None:
    import requests

    def boom(url: str, kw: dict):
        raise requests.Timeout("timed out")

    with pytest.raises(WestlakeError):
        fetch_detail("https://www.westlake.edu.cn/x.html", session=FakeSession(boom))