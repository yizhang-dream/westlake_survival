"""``westlake search`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

import json
from datetime import date

import pytest
from click.testing import CliRunner

from westlake_survival.exceptions import OffCampusError, ParseError
from westlake_survival.search import SearchHit, SearchResult, cli_group


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _result() -> SearchResult:
    return SearchResult(
        hits=[
            SearchHit(
                title="<font color=>西湖</font>理学讲坛",
                url="https://www.westlake.edu.cn/a.html",
                date=date(2026, 9, 23),
                author="",
                docchannel=4721,
            ),
            SearchHit(
                title="第二位",
                url="https://www.westlake.edu.cn/b.html",
                date=date(2026, 9, 22),
                author="全职",
            ),
        ],
        page=1,
        page_count=392,
        total=3916,
    )


@pytest.fixture
def fake_search(monkeypatch):
    """把 ``search.search`` 打桩，记录调用参数。"""
    calls: list[tuple[str, int]] = []

    def fake(keyword: str, page: int = 1, **kwargs):
        calls.append((keyword, page))
        return _result()

    monkeypatch.setattr("westlake_survival.search.search", fake)
    return calls


def test_cli_group_importable() -> None:
    from westlake_survival.search import cli_group as group

    assert group.name == "search"


def test_search_command_prints_table(runner: CliRunner, fake_search) -> None:
    result = runner.invoke(cli_group, ["西湖"])
    assert result.exit_code == 0, result.output
    assert "共 3916 条" in result.output
    assert "第 1/392 页" in result.output
    # 表格里是剥掉 font 标签后的标题
    assert "西湖理学讲坛" in result.output
    assert "<font" not in result.output
    assert fake_search == [("西湖", 1)]


def test_search_command_limit(runner: CliRunner, fake_search) -> None:
    result = runner.invoke(cli_group, ["西湖", "--limit", "1"])
    assert result.exit_code == 0
    assert "西湖理学讲坛" in result.output
    assert "第二位" not in result.output


def test_search_command_page(runner: CliRunner, fake_search) -> None:
    result = runner.invoke(cli_group, ["西湖", "--page", "2"])
    assert result.exit_code == 0
    assert fake_search == [("西湖", 2)]


def test_search_command_missing_keyword(runner: CliRunner) -> None:
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 2
    assert "缺少参数" in result.output


def test_search_command_no_hits(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr(
        "westlake_survival.search.search",
        lambda keyword, page=1, **kw: SearchResult(hits=[], page=1, page_count=0, total=0),
    )
    result = runner.invoke(cli_group, ["不存在的东西"])
    assert result.exit_code == 0
    assert "未找到匹配的内容" in result.output


def test_search_command_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(keyword: str, page: int = 1, **kw):
        raise ParseError("接口炸了")

    monkeypatch.setattr("westlake_survival.search.search", boom)
    result = runner.invoke(cli_group, ["西湖"])
    assert result.exit_code == 1
    assert "错误：接口炸了" in result.output


def test_search_command_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(keyword: str, page: int = 1, **kw):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.search.search", boom)
    result = runner.invoke(cli_group, ["西湖"])
    assert result.exit_code == 1
    assert "VPN" in result.output