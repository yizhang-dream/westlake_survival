"""contact 解析测试（离线，使用真实页面裁剪 fixture）。"""

from __future__ import annotations

import pytest

from westlake_survival.contact import (
    CAMPUS_NAMES,
    CampusInfo,
    ContactEntry,
    parse,
    parse_campuses,
    parse_contacts,
)
from westlake_survival.exceptions import ParseError


def test_three_campuses_parsed(page) -> None:
    """三校区按页面顺序解析，校区名归一化为云谷/云栖/铜鉴湖。"""
    assert [c.name for c in page.campuses] == list(CAMPUS_NAMES)


def test_campus_address_and_postcode(page) -> None:
    """地址去掉 ``<br>`` 与邮编段，邮编单独抽出。"""
    by_name = {c.name: c for c in page.campuses}
    assert by_name["云谷"].address == "浙江省杭州市西湖区墩余路600号"
    assert by_name["云谷"].postcode == "310030"
    assert by_name["云栖"].address == "浙江省杭州市西湖区石龙山街18号"
    assert by_name["云栖"].postcode == "310024"
    # 铜鉴湖园区地址里没有 ``</br>``，只有 ``<br>``，同样要能解析。
    assert by_name["铜鉴湖"].address == "浙江省杭州市西湖区转塘街道石龙山工业区块25号"
    assert by_name["铜鉴湖"].postcode == "310024"


def test_campus_traffic_text(page) -> None:
    """traffic 逐条带前缀：自驾按 ``<br/>`` 拆多条，地铁/公交附首末班。"""
    yungu = page.campuses[0]
    self_drives = [t for t in yungu.traffic if t.startswith("自驾：")]
    assert self_drives[0].startswith("自驾：1、杭长（宜）高速紫金港互通")
    assert len(self_drives) == 2  # fixture 裁到每校区两条自驾

    metro = next(t for t in yungu.traffic if t.startswith("地铁："))
    assert "4号线池华街站" in metro
    assert "池华街方向 首班车06:00，末班车22:40" in metro
    assert "浦沿方向 首班车06:00，末班车22:30" in metro

    bus = next(t for t in yungu.traffic if t.startswith("公交："))
    assert "西湖大学云谷校区，349路" in bus
    assert "三墩地铁站方向 首班车05:30，末班车21:30" in bus


def test_traffic_per_campus_from_own_entry(page) -> None:
    """``trafficList`` 按下标与 ``addressArr`` 对齐，各校区取自己的数据。"""
    by_name = {c.name: c for c in page.campuses}
    assert any("石龙山街云梦路口，121路" in t for t in by_name["云栖"].traffic)
    assert any("石龙山站，121路" in t for t in by_name["铜鉴湖"].traffic)
    # 铜鉴湖不应拿到云栖的公交站名
    assert not any("石龙山街云梦路口" in t for t in by_name["铜鉴湖"].traffic)


def test_map_url_absolute_and_missing(page) -> None:
    """mapList 相对路径拼成绝对 URL；铜鉴湖无地图故为 None。"""
    by_name = {c.name: c for c in page.campuses}
    assert by_name["云谷"].map_url.endswith("/address/yungu/202309/W020241028583928377634.png")
    assert by_name["云谷"].map_url.startswith("https://www.westlake.edu.cn/")
    assert by_name["云栖"].map_url.endswith("/address/yunqi/202309/W020241128382300898987.png")
    assert by_name["铜鉴湖"].map_url is None


def test_contacts_phones_and_emails(page) -> None:
    """contactList 解析出电话与邮箱，``0</span>571-…`` 被切开也能复原。"""
    by_label = {c.label: c for c in page.contacts}
    admissions = by_label["想咨询招生政策"]
    assert admissions.phones == ["0571-88996767", "0571-86886872"]
    assert admissions.emails == [
        "ugadmissions@westlake.edu.cn",
        "admissions@westlake.edu.cn",
    ]


def test_contacts_plain_text_has_no_tags(page) -> None:
    """纯文本已剥标签且不留 ``<``/``>``。"""
    for entry in page.contacts:
        assert "<" not in entry.text and ">" not in entry.text
    assert "西湖大学WestlakeUniversity" in next(
        c for c in page.contacts if c.label == "想参加校园活动"
    ).text


def test_contacts_phone_only_entry(page) -> None:
    """只有手机号的条目：抽到手机号，邮箱为空。"""
    donate = next(c for c in page.contacts if c.label == "想捐赠支持西湖")
    assert donate.phones == ["13071113309"]
    assert donate.emails == []


def test_parse_campus_helpers(page, fixture_text: str) -> None:
    """便捷包装 :func:`parse_campuses` / :func:`parse_contacts` 与 ``parse`` 一致。"""
    assert parse_campuses(fixture_text) == page.campuses
    assert parse_contacts(fixture_text) == page.contacts


def test_general_contacts_constant() -> None:
    """:data:`GENERAL_CONTACTS` 常量对齐 2026-09-22 首页页脚实测值。"""
    from westlake_survival.contact import GENERAL_CONTACTS

    assert GENERAL_CONTACTS.phones == ["0571-86886861"]
    assert GENERAL_CONTACTS.emails == ["media@westlake.edu.cn"]
    assert GENERAL_CONTACTS.fax == "0571-88111699"


def test_dataclass_defaults() -> None:
    """模型可空构造，便于调用方手工拼装。"""
    info = CampusInfo(name="云谷")
    assert info.address == "" and info.postcode == "" and info.traffic == []
    assert info.map_url is None
    entry = ContactEntry(label="X")
    assert entry.phones == [] and entry.emails == [] and entry.text == ""


def test_error_mapping_missing_component() -> None:
    """页面里没有 contactUs 组件 → ParseError。"""
    with pytest.raises(ParseError, match="contactUs"):
        parse("<html><body>空壳页面</body></html>")


def test_error_mapping_missing_key() -> None:
    """有组件但缺少 mapList 键 → ParseError 指出缺失键名。"""
    html = 'new contactUs("#app", { transportObj: { addressArr: [], trafficList: [] } });'
    with pytest.raises(ParseError, match="mapList"):
        parse(html)
