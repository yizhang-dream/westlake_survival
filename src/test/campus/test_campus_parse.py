"""``westlake_survival.campus`` 的离线解析测试（fixture 为真实页面裁剪）。"""

from __future__ import annotations

import pytest

from westlake_survival.campus import (
    CAMPUS_CHOICES,
    DINING_KINDS,
    HOUSING_DINING_URL,
    SHUTTLE_LIVE_URL,
    CampusData,
    CampusService,
    DiningSpot,
    Housing,
    _split_lines,
    parse_campus,
)
from westlake_survival.exceptions import ParseError


# --------------------------------------------------------------------------- #
# 文本工具
# --------------------------------------------------------------------------- #
def test_split_lines_handles_all_br_variants() -> None:
    assert _split_lines("a</br>b<br/>c<br>d</br>e") == ["a", "b", "c", "d", "e"]


def test_split_lines_handles_paragraph_boundary_and_strips_tags() -> None:
    html = "周一至周五 07:30-19:00</span></p><p>周六至周日 08:00-17:00</p>"
    assert _split_lines(html) == ["周一至周五 07:30-19:00", "周六至周日 08:00-17:00"]


def test_split_lines_empty_and_blank_lines_dropped() -> None:
    assert _split_lines("") == []
    assert _split_lines("<p></p></br></br>") == []


# --------------------------------------------------------------------------- #
# 整页解析
# --------------------------------------------------------------------------- #
def test_parse_fixture_dining_kinds(campus_data: CampusData) -> None:
    assert set(campus_data.dining) == set(DINING_KINDS)
    assert len(campus_data.dining["食堂"]) == 3
    assert len(campus_data.dining["咖啡轻食"]) == 3


def test_parse_fixture_dining_fields(campus_data: CampusData) -> None:
    spot = campus_data.dining["食堂"][0]
    assert isinstance(spot, DiningSpot)
    assert spot.name == "C17食堂"
    assert spot.campus == "云谷"
    assert spot.address == "云谷校区C17"
    assert "中式快餐" in spot.food
    assert spot.hours == [
        "早餐时间: 06:45-9:00",
        "午餐时间: 11:00-13:00",
        "晚餐时间: 17:00-19:00",
        "夜宵时间: 19:30-23:00",
    ]


def test_parse_fixture_housing_and_phone(campus_data: CampusData) -> None:
    houses = {h.name: h for h in campus_data.housing}
    assert set(houses) == {"本科生公寓", "研究生公寓", "学生公寓"}
    grad = houses["研究生公寓"]
    assert isinstance(grad, Housing)
    assert grad.campus == "云谷"
    assert grad.address == "C11-C15，F12-F15"
    assert grad.phone == "0571-88888888"
    assert grad.services[0] == "24小时管家服务"
    assert grad.services[-1].startswith("公寓配套：")
    # 空电话保留为空串
    assert houses["本科生公寓"].phone == ""


def test_parse_fixture_services(campus_data: CampusData) -> None:
    services = {s.name: s for s in campus_data.services}
    assert set(services) == {"校园超市", "理发服务"}
    market = services["校园超市"]
    assert isinstance(market, CampusService)
    assert market.campus == "云谷"
    assert "无人自助" in market.hours
    assert "24小时" in market.hours


def test_parse_fixture_notices_and_shuttle_url(campus_data: CampusData) -> None:
    # 交通方式块的 notice 含实时班车外链
    notice = campus_data.shuttle_notice()
    assert SHUTTLE_LIVE_URL in notice
    assert "h5shuttleRoute" in notice
    # 食堂块的反馈文案也保留下来
    assert "food@westlake.edu.cn" in campus_data.notices["食堂"]


def test_shuttle_live_url_is_absolute() -> None:
    assert SHUTTLE_LIVE_URL.startswith("https://security.zjwsvip.com/#/h5shuttleRoute/")


def test_page_url_and_campus_choices() -> None:
    assert HOUSING_DINING_URL.endswith("/campus_life/housing_dining/")
    assert CAMPUS_CHOICES == ("云谷", "云栖")


def test_parse_campus_normalizes_label(fixture_text: str) -> None:
    # fixture 的 label 是 "云谷校区"，解析后应统一为 "云谷"
    data = parse_campus(fixture_text)
    assert all(spot.campus == "云谷" for spot in data.dining["食堂"] if spot.name != "6号楼食堂")


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
def test_parse_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_campus("<html>没有任何组件</html>")


def test_parse_missing_alldata_raises() -> None:
    html = '<script>new housingDining("#app", { title: "x" });</script>'
    with pytest.raises(ParseError):
        parse_campus(html)


def test_parse_unbalanced_array_raises() -> None:
    html = '<script>new housingDining("#app", { allData: [ { keyword: "食堂" '
    with pytest.raises(ParseError):
        parse_campus(html)