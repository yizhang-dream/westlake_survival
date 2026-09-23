"""``westlake research`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from click.testing import CliRunner

from westlake_survival.exceptions import OffCampusError, ParseError
from westlake_survival.research import ResearchDetail, ResearchItem, cli_group


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _items() -> list[ResearchItem]:
    base = "https://www.westlake.edu.cn/research/research_at_westlake"
    return [
        ResearchItem(
            title="西湖大学卢培龙研究团队及其合作者从头设计新型电压门控阴离子通道",
            category="生命健康 / Good Health & Wellbeing",
            summary="西湖大学卢培龙研究团队及其合作者从头设计新型电压门控阴离子通道",
            date=datetime(2025, 10, 16),
            url=f"{base}/good_health_wellbeing/202510/t20251016_60343.html",
            img_url="./x.jpg",
        ),
        ResearchItem(
            title="免疫细胞“王牌情报员”cDC1的突围之战 | Science报道",
            category="医学创新 / Treatment & Cures for Diseases",
            date=datetime(2025, 11, 14),
            url=f"{base}/Research/202511/t20251114_61277.html",
        ),
    ]


@pytest.fixture
def fake_latest(monkeypatch):
    """把 ``research.latest`` 打桩，记录调用参数。"""
    calls: list[tuple[str | None, int | None]] = []

    def fake(category=None, limit=None, **kwargs):
        calls.append((category, limit))
        return _items()

    monkeypatch.setattr("westlake_survival.research.latest", fake)
    return calls


def test_cli_group_importable() -> None:
    from westlake_survival.research import cli_group as group

    assert group.name == "research"


def test_research_list_prints_table(runner: CliRunner, fake_latest) -> None:
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 0, result.output
    assert "西湖大学卢培龙研究团队" in result.output
    assert "生命健康 / Good Health & Wellbeing" in result.output
    assert "2025-10-16" in result.output
    assert fake_latest == [(None, 10)]


def test_research_list_category_and_limit(runner: CliRunner, fake_latest) -> None:
    result = runner.invoke(cli_group, ["--category", "医学创新 / Treatment & Cures for Diseases", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert fake_latest == [("医学创新 / Treatment & Cures for Diseases", 1)]


def test_research_list_empty(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.research.latest", lambda *a, **k: [])
    result = runner.invoke(cli_group, ["--category", "不存在"])

    assert result.exit_code == 0
    assert "未找到" in result.output


def test_research_list_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(*a, **k):
        raise ParseError("页面炸了")

    monkeypatch.setattr("westlake_survival.research.latest", boom)
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 1
    assert "错误：页面炸了" in result.output


def test_research_list_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(*a, **k):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.research.latest", boom)
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 1
    assert "VPN" in result.output


def test_research_detail_prints_fields(runner: CliRunner, monkeypatch) -> None:
    url = "https://www.westlake.edu.cn/research/research_at_westlake/good_health_wellbeing/202510/t20251016_60343.html"
    captured: list[str] = []

    def fake(url_arg, **kwargs):
        captured.append(url_arg)
        return ResearchDetail(
            title="西湖大学卢培龙研究团队及其合作者从头设计新型电压门控阴离子通道",
            author="",
            category="学术",
            date=datetime(2025, 10, 16, 21, 59, 19),
            content_html="<p>正文第一段</p><p>正文第二段</p>",
            url=url_arg,
        )

    monkeypatch.setattr("westlake_survival.research.fetch_detail", fake)
    result = runner.invoke(cli_group, ["detail", url])

    assert result.exit_code == 0, result.output
    assert "西湖大学卢培龙研究团队" in result.output
    assert "学术" in result.output
    assert "2025-10-16 21:59:19" in result.output
    assert "正文第一段" in result.output
    assert "<p>" not in result.output
    assert captured == [url]


def test_research_detail_requires_url(runner: CliRunner) -> None:
    result = runner.invoke(cli_group, ["detail"])

    assert result.exit_code == 2
    assert "Missing argument" in result.output or "缺少" in result.output


def test_research_detail_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(url, **kwargs):
        raise ParseError("详情炸了")

    monkeypatch.setattr("westlake_survival.research.fetch_detail", boom)
    result = runner.invoke(cli_group, ["detail", "https://x/d.html"])

    assert result.exit_code == 1
    assert "错误：详情炸了" in result.output
