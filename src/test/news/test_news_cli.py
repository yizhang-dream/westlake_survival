"""``westlake news`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from click.testing import CliRunner

from westlake_survival.exceptions import OffCampusError, ParseError
from westlake_survival.news import NewsDetail, NewsItem, cli_group


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _items() -> list[NewsItem]:
    base = "https://www.westlake.edu.cn/news_events/westlakenews"
    return [
        NewsItem(
            title="本校“最大气”的两位老师！",
            category="人物",
            date=datetime(2026, 9, 22, 11, 24, 35),
            url=f"{base}/people/202609/t20260922_69940.html",
            img_url="../people/202609/x.jpg",
        ),
        NewsItem(
            title="73个“小小宇宙”，等你来投下一颗星",
            category="资讯",
            date=datetime(2026, 9, 21, 17, 18, 49),
            url=f"{base}/News/202609/t20260921_69914.html",
        ),
    ]


@pytest.fixture
def fake_latest(monkeypatch):
    """把 ``news.latest`` 打桩，记录调用参数。"""
    calls: list[tuple[str | None, int | None]] = []

    def fake(category=None, limit=None, **kwargs):
        calls.append((category, limit))
        return _items()

    monkeypatch.setattr("westlake_survival.news.latest", fake)
    return calls


def test_cli_group_importable() -> None:
    from westlake_survival.news import cli_group as group

    assert group.name == "news"


def test_news_list_prints_table(runner: CliRunner, fake_latest) -> None:
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 0, result.output
    assert "本校“最大气”的两位老师！" in result.output
    assert "人物" in result.output
    assert "2026-09-22 11:24" in result.output
    assert fake_latest == [(None, 10)]


def test_news_list_category_and_limit(runner: CliRunner, fake_latest) -> None:
    result = runner.invoke(cli_group, ["--category", "人物", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert fake_latest == [("人物", 1)]


def test_news_list_empty(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.news.latest", lambda *a, **k: [])
    result = runner.invoke(cli_group, ["--category", "不存在"])

    assert result.exit_code == 0
    assert "未找到" in result.output


def test_news_list_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(*a, **k):
        raise ParseError("页面炸了")

    monkeypatch.setattr("westlake_survival.news.latest", boom)
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 1
    assert "错误：页面炸了" in result.output


def test_news_list_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(*a, **k):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.news.latest", boom)
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 1
    assert "VPN" in result.output


def test_news_detail_prints_fields(runner: CliRunner, monkeypatch) -> None:
    url = "https://www.westlake.edu.cn/news_events/westlakenews/people/202609/t20260922_69940.html"
    captured: list[str] = []

    def fake(url_arg, **kwargs):
        captured.append(url_arg)
        return NewsDetail(
            title="本校“最大气”的两位老师！",
            author="",
            category="人物",
            date=datetime(2026, 9, 22, 11, 24, 35),
            content_html="<p>正文第一段</p><p>正文第二段</p>",
            url=url_arg,
        )

    monkeypatch.setattr("westlake_survival.news.fetch_detail", fake)
    result = runner.invoke(cli_group, ["detail", url])

    assert result.exit_code == 0, result.output
    assert "本校“最大气”的两位老师！" in result.output
    assert "人物" in result.output
    assert "2026-09-22 11:24:35" in result.output
    assert "正文第一段" in result.output
    assert "<p>" not in result.output
    assert captured == [url]


def test_news_detail_requires_url(runner: CliRunner) -> None:
    result = runner.invoke(cli_group, ["detail"])

    assert result.exit_code == 2
    assert "Missing argument" in result.output or "缺少" in result.output


def test_news_detail_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(url, **kwargs):
        raise ParseError("详情炸了")

    monkeypatch.setattr("westlake_survival.news.fetch_detail", boom)
    result = runner.invoke(cli_group, ["detail", "https://x/d.html"])

    assert result.exit_code == 1
    assert "错误：详情炸了" in result.output