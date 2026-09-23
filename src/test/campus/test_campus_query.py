"""``westlake_survival.campus`` 的查询 API 与网络层测试（离线，全部打桩）。"""

from __future__ import annotations

import pytest
import requests

from campus_fakes import FakeResponse, FakeSession
from westlake_survival import campus as campus_mod
from westlake_survival.campus import (
    CampusData,
    dining,
    housing,
    load,
    parse_campus,
    services,
)
from westlake_survival.exceptions import OffCampusError, ParseError, WestlakeError


@pytest.fixture
def data(fixture_text: str, monkeypatch) -> CampusData:
    """把解析好的 fixture 数据注入模块单例，供查询 API 使用。"""
    parsed = parse_campus(fixture_text)
    monkeypatch.setattr(campus_mod, "_instance", parsed)
    return parsed


# --------------------------------------------------------------------------- #
# kind / campus 过滤
# --------------------------------------------------------------------------- #
def test_dining_default_returns_both_kinds(data: CampusData) -> None:
    spots = dining()
    assert len(spots) == 6
    assert {s.name for s in spots} >= {"C17食堂", "行政楼咖啡吧"}


def test_dining_kind_filter(data: CampusData) -> None:
    canteens = dining(kind="食堂")
    assert len(canteens) == 3
    assert all(s.name.endswith("食堂") for s in canteens)

    coffee = dining(kind="咖啡轻食")
    assert len(coffee) == 3
    assert {s.name for s in coffee} == {"行政楼咖啡吧", "面包店", "咖啡吧"}


def test_dining_campus_filter(data: CampusData) -> None:
    yungu = dining(campus="云谷")
    assert yungu
    assert all(s.campus == "云谷" for s in yungu)

    yunqi_canteen = dining(kind="食堂", campus="云栖")
    assert [s.name for s in yunqi_canteen] == ["6号楼食堂"]


def test_dining_campus_accepts_suffix(data: CampusData) -> None:
    # 传入带「校区」尾缀也能匹配（页面 label 是「云谷校区」）
    assert {s.name for s in dining(campus="云谷校区")} == {s.name for s in dining(campus="云谷")}


def test_dining_unknown_campus_returns_empty(data: CampusData) -> None:
    assert dining(campus="不存在") == []


def test_dining_invalid_kind_raises(data: CampusData) -> None:
    with pytest.raises(ValueError):
        dining(kind="夜宵")


def test_housing_campus_filter(data: CampusData) -> None:
    assert len(housing()) == 3
    yunqi = housing(campus="云栖")
    assert [h.name for h in yunqi] == ["学生公寓"]
    assert yunqi[0].phone == ""


def test_services_campus_filter(data: CampusData) -> None:
    assert {s.name for s in services()} == {"校园超市", "理发服务"}
    assert all(s.campus == "云谷" for s in services(campus="云谷"))


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
@pytest.fixture
def temp_home(tmp_path, monkeypatch):
    """把缓存目录重定向到临时目录，避免污染真实 ``~/.westlake_survival``。"""
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))
    return tmp_path


def test_load_decodes_content_not_text(fixture_text: str, temp_home) -> None:
    """响应无 charset：必须走 content 字节路径，否则中文乱码。"""
    session = FakeSession(lambda url, kw: FakeResponse(fixture_text, url=url))
    data = load(session=session)
    assert len(data.dining["食堂"]) == 3
    assert data.dining["食堂"][0].name == "C17食堂"
    # 确实请求了页面
    assert session.calls[0][0].endswith("/campus_life/housing_dining/")


def test_load_304_uses_cached_body(fixture_text: str, temp_home) -> None:
    first = FakeSession(
        lambda url, kw: FakeResponse(fixture_text, headers={"ETag": 'W/"abc"'}, url=url)
    )
    load(session=first)
    # 第二次带 If-None-Match，服务器回 304 → 用缓存体
    second = FakeSession(lambda url, kw: FakeResponse(b"", status=304, url=url))
    data = load(session=second)
    assert data.dining["食堂"][0].name == "C17食堂"
    assert second.calls[0][1]["headers"].get("If-None-Match") == 'W/"abc"'


def test_load_403_offcampus(temp_home) -> None:
    marker = b"Access forbidden, please contact administrator"
    session = FakeSession(lambda url, kw: FakeResponse(marker, status=403, url=url))
    with pytest.raises(OffCampusError):
        load(session=session)


def test_load_http_500_maps_to_parse_error(temp_home) -> None:
    session = FakeSession(lambda url, kw: FakeResponse(b"oops", status=500, url=url))
    with pytest.raises(ParseError):
        load(session=session)


def test_load_timeout_maps_to_westlake_error(temp_home) -> None:
    def boom(url, kw):
        raise requests.Timeout("slow")

    with pytest.raises(WestlakeError):
        load(session=FakeSession(boom))


def test_load_connection_error_maps_to_westlake_error(temp_home) -> None:
    def boom(url, kw):
        raise requests.ConnectionError("down")

    with pytest.raises(WestlakeError):
        load(session=FakeSession(boom))


def test_load_bad_structure_maps_to_parse_error(temp_home) -> None:
    session = FakeSession(lambda url, kw: FakeResponse("<html>空</html>", url=url))
    with pytest.raises(ParseError):
        load(session=session)