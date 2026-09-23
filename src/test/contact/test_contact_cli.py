"""``westlake contact`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.contact import CAMPUS_NAMES, CampusInfo, ContactEntry, cli_group
from westlake_survival.exceptions import OffCampusError, ParseError

_FAKE_CAMPUSES = [
    CampusInfo(
        name="云谷",
        address="浙江省杭州市西湖区墩余路600号",
        postcode="310030",
        traffic=["自驾：1、杭长高速 – 墩余路", "地铁：4号线池华街站"],
        map_url="https://www.westlake.edu.cn/about/contact_us/address/yungu/x.png",
    ),
    CampusInfo(
        name="云栖",
        address="浙江省杭州市西湖区石龙山街18号",
        postcode="310024",
        traffic=["公交：石龙山街云梦路口，121路"],
        map_url="https://www.westlake.edu.cn/about/contact_us/address/yunqi/y.png",
    ),
    CampusInfo(name="铜鉴湖", address="浙江省杭州市西湖区转塘街道石龙山工业区块25号", postcode="310024"),
]

_FAKE_CONTACTS = [
    ContactEntry(
        label="想咨询招生政策",
        phones=["0571-88996767", "0571-86886872"],
        emails=["ugadmissions@westlake.edu.cn", "admissions@westlake.edu.cn"],
    ),
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_campuses(monkeypatch):
    calls: list[bool] = []

    def fake(refresh: bool = False, **kwargs):
        calls.append(refresh)
        return _FAKE_CAMPUSES

    monkeypatch.setattr("westlake_survival.contact.campuses", fake)
    return calls


@pytest.fixture
def fake_contacts(monkeypatch):
    monkeypatch.setattr("westlake_survival.contact.contacts", lambda **kw: _FAKE_CONTACTS)


def test_cli_group_name() -> None:
    assert cli_group.name == "contact"


def test_contact_lists_three_campuses(runner, fake_campuses) -> None:
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0, result.output
    for name in CAMPUS_NAMES:
        assert f"【{name}校区】" in result.output
    assert "浙江省杭州市西湖区墩余路600号" in result.output
    assert "自驾：1、杭长高速 – 墩余路" in result.output
    assert fake_campuses == [False]


def test_contact_campus_filter(runner, fake_campuses) -> None:
    result = runner.invoke(cli_group, ["--campus", "铜鉴湖"])
    assert result.exit_code == 0, result.output
    assert "【铜鉴湖校区】" in result.output
    assert "云谷校区" not in result.output
    assert "石龙山工业区块25号" in result.output


def test_contact_campus_filter_yungu(runner, fake_campuses) -> None:
    result = runner.invoke(cli_group, ["--campus", "云谷"])
    assert result.exit_code == 0
    assert "【云谷校区】" in result.output
    assert "石龙山街18号" not in result.output


def test_contact_campus_invalid_choice(runner) -> None:
    """非法校区名由 click.Choice 拦下（退出码 2）。"""
    result = runner.invoke(cli_group, ["--campus", "不存在"])
    assert result.exit_code == 2


def test_contact_no_match(runner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.contact.campuses", lambda **kw: [])
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0
    assert "未找到匹配的校区信息" in result.output


def test_contact_phones(runner, fake_contacts) -> None:
    result = runner.invoke(cli_group, ["phones"])
    assert result.exit_code == 0, result.output
    assert "想咨询招生政策" in result.output
    assert "0571-88996767" in result.output
    assert "admissions@westlake.edu.cn" in result.output


def test_contact_phones_includes_general_footer(runner, fake_contacts) -> None:
    """phones 命令附上页脚公共事务部常量。"""
    result = runner.invoke(cli_group, ["phones"])
    assert "0571-86886861" in result.output
    assert "media@westlake.edu.cn" in result.output
    assert "0571-88111699" in result.output


def test_contact_error_exit_code(runner, monkeypatch) -> None:
    def boom(**kw):
        raise ParseError("页面炸了")

    monkeypatch.setattr("westlake_survival.contact.campuses", boom)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 1
    assert "错误：页面炸了" in result.output


def test_contact_offcampus_hint(runner, monkeypatch) -> None:
    def boom(**kw):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.contact.campuses", boom)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 1
    assert "VPN" in result.output
