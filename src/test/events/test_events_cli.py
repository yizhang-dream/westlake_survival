"""``westlake events`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from click.testing import CliRunner

from westlake_survival.events import EventDetail, EventItem, cli_group
from westlake_survival.exceptions import OffCampusError, ParseError


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _items() -> list[EventItem]:
    return [
        EventItem(
            title="西湖理学讲坛| 程金光",
            date=datetime(2026, 9, 23, 14, 0),
            event_type="名家讲座",
            venue="云谷校区E10-211",
            organizer="理学院",
            url="https://www.westlake.edu.cn/a.html",
        ),
        EventItem(
            title="生命科学名师论坛",
            date=datetime(2026, 9, 24, 13, 30),
            event_type="学术会议",
            venue="云谷校区E9-109",
            organizer="生命科学学院",
            url="https://www.westlake.edu.cn/b.html",
        ),
    ]


@pytest.fixture
def fake_upcoming(monkeypatch):
    """把 ``events.upcoming`` 打桩，记录调用参数。"""
    calls: list[int] = []

    def fake(days: int = 14, **kwargs):
        calls.append(days)
        return _items()

    monkeypatch.setattr("westlake_survival.events.upcoming", fake)
    return calls


def test_cli_group_importable() -> None:
    assert cli_group.name == "events"


def test_events_command_prints_table(runner: CliRunner, fake_upcoming) -> None:
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0, result.output
    assert "西湖理学讲坛| 程金光" in result.output
    assert "云谷校区E10-211" in result.output
    assert "理学院" in result.output
    assert "2026-09-23 14:00" in result.output
    assert fake_upcoming == [14]


def test_events_command_days_option(runner: CliRunner, fake_upcoming) -> None:
    result = runner.invoke(cli_group, ["--days", "3"])
    assert result.exit_code == 0
    assert fake_upcoming == [3]


def test_events_command_type_filter(runner: CliRunner, fake_upcoming) -> None:
    result = runner.invoke(cli_group, ["--type", "学术会议"])
    assert result.exit_code == 0
    assert "生命科学名师论坛" in result.output
    assert "西湖理学讲坛| 程金光" not in result.output


def test_events_command_limit(runner: CliRunner, fake_upcoming) -> None:
    result = runner.invoke(cli_group, ["--limit", "1"])
    assert result.exit_code == 0
    assert "西湖理学讲坛| 程金光" in result.output
    assert "生命科学名师论坛" not in result.output


def test_events_command_negative_days(runner: CliRunner, fake_upcoming) -> None:
    result = runner.invoke(cli_group, ["--days", "-1"])
    assert result.exit_code == 2
    assert "--days 必须 >= 0" in result.output


def test_events_command_no_items(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.events.upcoming", lambda days=14, **kw: [])
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0
    assert "暂无活动预告" in result.output


def test_events_command_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(days: int = 14, **kwargs):
        raise ParseError("列表页炸了")

    monkeypatch.setattr("westlake_survival.events.upcoming", boom)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 1
    assert "错误：列表页炸了" in result.output


def test_events_command_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(days: int = 14, **kwargs):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.events.upcoming", boom)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 1
    assert "VPN" in result.output


def test_events_detail_command(runner: CliRunner, monkeypatch) -> None:
    detail = EventDetail(
        title="西湖理学讲坛| 程金光",
        date_text="2026-09-23 14:00:00",
        time_text="2026-09-23 14:00 - 2026-09-23 15:30",
        venue="云谷校区E10-211",
        host="林效 副教授",
        audience="全校师生",
        category="名家讲座",
        content_html="<p>正文</p>",
        url="https://www.westlake.edu.cn/a.html",
    )
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs):
        seen.append(url)
        return detail

    monkeypatch.setattr("westlake_survival.events.fetch_detail", fake_fetch)
    result = runner.invoke(cli_group, ["detail", "https://www.westlake.edu.cn/a.html"])
    assert result.exit_code == 0, result.output
    assert seen == ["https://www.westlake.edu.cn/a.html"]
    assert "西湖理学讲坛| 程金光" in result.output
    assert "林效 副教授" in result.output
    assert "全校师生" in result.output
    assert "<p>正文</p>" in result.output


def test_events_detail_command_error(runner: CliRunner, monkeypatch) -> None:
    def boom(url: str, **kwargs):
        raise ParseError("详情页炸了")

    monkeypatch.setattr("westlake_survival.events.fetch_detail", boom)
    result = runner.invoke(cli_group, ["detail", "https://x/y.html"])
    assert result.exit_code == 1
    assert "错误：详情页炸了" in result.output


def test_events_detail_requires_url(runner: CliRunner) -> None:
    result = runner.invoke(cli_group, ["detail"])
    assert result.exit_code == 2
    assert "Missing argument" in result.output or "缺少" in result.output