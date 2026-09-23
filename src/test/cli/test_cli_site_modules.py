"""官网内容模块接入顶层命令树的集成测试（离线，网络层打桩）。

覆盖：7 个新命令组挂在 ``westlake`` 顶层；抽 2 个命令（search / events）
走顶层命令树用 ``CliRunner`` 跑通。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from click.testing import CliRunner

from westlake_survival.events import EventItem
from westlake_survival.search import SearchHit, SearchResult

#: 本次接入的 7 个官网内容命令组。
_SITE_COMMANDS = (
    "search",
    "news",
    "events",
    "careers",
    "faculty",
    "campus",
    "contact",
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_top_level_help_lists_site_commands(runner: CliRunner, cli_group) -> None:
    """``westlake --help`` 能看到全部 7 个新命令组。"""
    result = runner.invoke(cli_group, ["--help"])
    assert result.exit_code == 0, result.output
    for name in _SITE_COMMANDS:
        assert name in result.output


def test_site_commands_registered_on_cli(cli_group) -> None:
    """7 个新命令组都真实注册在顶层 group 上（而非仅出现在 help 文本）。"""
    for name in _SITE_COMMANDS:
        assert name in cli_group.commands


def test_top_level_search_command(runner: CliRunner, cli_group, monkeypatch) -> None:
    """``westlake search 西湖 --limit 2`` 走顶层命令树并打印结果。"""
    calls: list[tuple[str, int]] = []

    def fake(keyword: str, page: int = 1, **kwargs):
        calls.append((keyword, page))
        return SearchResult(
            hits=[
                SearchHit(
                    title="<font color=>西湖</font>理学讲坛",
                    url="https://www.westlake.edu.cn/a.html",
                    date=date(2026, 9, 23),
                ),
                SearchHit(
                    title="第二位",
                    url="https://www.westlake.edu.cn/b.html",
                    date=date(2026, 9, 22),
                ),
            ],
            page=1,
            page_count=392,
            total=3916,
        )

    monkeypatch.setattr("westlake_survival.search.search", fake)
    result = runner.invoke(cli_group, ["search", "西湖", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert calls == [("西湖", 1)]
    assert "西湖理学讲坛" in result.output
    assert "第二位" in result.output


def test_top_level_events_command(runner: CliRunner, cli_group, monkeypatch) -> None:
    """``westlake events --days 3`` 走顶层命令树并打印活动表格。"""
    calls: list[int] = []

    def fake(days: int = 14, **kwargs):
        calls.append(days)
        return [
            EventItem(
                title="西湖理学讲坛| 程金光",
                date=datetime(2026, 9, 23, 14, 0),
                event_type="名家讲座",
                venue="云谷校区E10-211",
            )
        ]

    monkeypatch.setattr("westlake_survival.events.upcoming", fake)
    result = runner.invoke(cli_group, ["events", "--days", "3"])
    assert result.exit_code == 0, result.output
    assert calls == [3]
    assert "西湖理学讲坛| 程金光" in result.output
    assert "云谷校区E10-211" in result.output


def test_top_level_campus_command(runner: CliRunner, cli_group, monkeypatch) -> None:
    """``westlake campus dining`` 走顶层命令树（网络层打桩）。"""
    from westlake_survival.campus import DiningSpot

    monkeypatch.setattr(
        "westlake_survival.campus.dining",
        lambda kind=None, campus=None: [
            DiningSpot(name="云谷食堂", campus="云谷", address="E1", food="自助")
        ],
    )
    result = runner.invoke(cli_group, ["campus", "dining"])
    assert result.exit_code == 0, result.output
    assert "云谷食堂" in result.output