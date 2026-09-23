"""``westlake campus`` 命令组测试（离线，查询 API 打桩）。"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.campus import (
    CampusService,
    DiningSpot,
    Housing,
    cli_group,
)
from westlake_survival.exceptions import OffCampusError, ParseError


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_data(monkeypatch):
    """把 campus 模块的三个查询 API 打桩，记录调用参数。"""
    calls: list[tuple] = []
    spots = [
        DiningSpot(
            name="C17食堂",
            campus="云谷",
            address="云谷校区C17",
            food="中式快餐",
            hours=["早餐时间: 06:45-9:00", "午餐时间: 11:00-13:00"],
        ),
        DiningSpot(name="行政楼咖啡吧", campus="云谷", address="A1#一楼", hours=["周一至周日 8:00-20:00"]),
    ]
    houses = [
        Housing(
            name="研究生公寓",
            campus="云谷",
            address="C11-C15",
            services=["24小时管家服务", "2人套单间"],
            phone="0571-88888888",
        )
    ]

    def fake_dining(kind=None, campus=None):
        calls.append(("dining", kind, campus))
        return spots

    def fake_housing(campus=None):
        calls.append(("housing", campus))
        return houses

    def fake_services(campus=None):
        calls.append(("services", campus))
        return [CampusService(name="校园超市", campus="云谷", address="C19#1楼", hours=["24小时"])]

    monkeypatch.setattr("westlake_survival.campus.dining", fake_dining)
    monkeypatch.setattr("westlake_survival.campus.housing", fake_housing)
    monkeypatch.setattr("westlake_survival.campus.services", fake_services)
    return calls


def test_cli_group_importable() -> None:
    assert cli_group.name == "campus"
    assert set(cli_group.commands) == {"dining", "housing"}


def test_dining_command_prints_table(runner: CliRunner, fake_data) -> None:
    result = runner.invoke(cli_group, ["dining"])
    assert result.exit_code == 0, result.output
    assert "C17食堂" in result.output
    assert "行政楼咖啡吧" in result.output
    assert "早餐时间: 06:45-9:00" in result.output
    assert fake_data == [("dining", None, None)]


def test_dining_command_kind_and_campus(runner: CliRunner, fake_data) -> None:
    result = runner.invoke(cli_group, ["dining", "--kind", "食堂", "--campus", "云谷"])
    assert result.exit_code == 0, result.output
    assert fake_data == [("dining", "食堂", "云谷")]


def test_dining_command_invalid_kind_rejected(runner: CliRunner, fake_data) -> None:
    result = runner.invoke(cli_group, ["dining", "--kind", "夜宵"])
    assert result.exit_code == 2
    assert not fake_data  # 未调用 API


def test_dining_command_invalid_campus_rejected(runner: CliRunner, fake_data) -> None:
    result = runner.invoke(cli_group, ["dining", "--campus", "铜鉴湖"])
    assert result.exit_code == 2
    assert not fake_data


def test_dining_command_no_results(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.campus.dining", lambda kind=None, campus=None: [])
    result = runner.invoke(cli_group, ["dining"])
    assert result.exit_code == 0
    assert "未找到匹配的餐饮点" in result.output


def test_housing_command_prints_table(runner: CliRunner, fake_data) -> None:
    result = runner.invoke(cli_group, ["housing", "--campus", "云谷"])
    assert result.exit_code == 0, result.output
    assert "研究生公寓" in result.output
    assert "0571-88888888" in result.output
    assert fake_data == [("housing", "云谷")]


def test_dining_command_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(kind=None, campus=None):
        raise ParseError("页面炸了")

    monkeypatch.setattr("westlake_survival.campus.dining", boom)
    result = runner.invoke(cli_group, ["dining"])
    assert result.exit_code == 1
    assert "错误：页面炸了" in result.output


def test_dining_command_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(kind=None, campus=None):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.campus.dining", boom)
    result = runner.invoke(cli_group, ["dining"])
    assert result.exit_code == 1
    assert "VPN" in result.output