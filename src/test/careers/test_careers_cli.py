"""``westlake careers`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

from datetime import date

import pytest
from click.testing import CliRunner

from westlake_survival.careers import Position, PositionDetail, cli_group
from westlake_survival.exceptions import OffCampusError, ParseError


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _positions() -> list[Position]:
    return [
        Position(
            title="西湖大学医学院钟声实验室研究系列招聘",
            category="科研团队",
            job_type="全职",
            department="医学院",
            location="中国杭州",
            date=date(2026, 9, 18),
            url="https://www.westlake.edu.cn/a.html",
        ),
        Position(
            title="西湖大学工学院宫先达实验室博士后招聘启事",
            category="博士后",
            job_type="全职",
            department="工学院",
            location="中国杭州，云谷校区",
            date=date(2026, 9, 18),
            url="https://www.westlake.edu.cn/b.html",
            external_url="https://app.mokahr.com/x",
        ),
    ]


@pytest.fixture
def fake_positions(monkeypatch):
    """把 ``careers.positions`` 打桩，记录调用参数。"""
    calls: list[dict] = []

    def fake(category=None, keyword=None, limit=None, **kwargs):
        calls.append({"category": category, "keyword": keyword, "limit": limit})
        return _positions()[: (limit if limit is not None else len(_positions()))]

    monkeypatch.setattr("westlake_survival.careers.positions", fake)
    return calls


def test_cli_group_importable() -> None:
    from westlake_survival.careers import cli_group as group

    assert group.name == "careers"


def test_careers_lists_table(runner: CliRunner, fake_positions) -> None:
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 0, result.output
    assert "共 2 条" in result.output
    assert "西湖大学医学院钟声实验室研究系列招聘" in result.output
    # 表格含类别/部门/地点列
    assert "科研团队" in result.output
    assert "医学院" in result.output
    assert fake_positions == [{"category": None, "keyword": None, "limit": 20}]


def test_careers_category_option(runner: CliRunner, fake_positions) -> None:
    result = runner.invoke(cli_group, ["--category", "博士后"])

    assert result.exit_code == 0, result.output
    assert fake_positions[0]["category"] == "博士后"


def test_careers_keyword_option(runner: CliRunner, fake_positions) -> None:
    result = runner.invoke(cli_group, ["--keyword", "钟声"])

    assert result.exit_code == 0, result.output
    assert fake_positions[0]["keyword"] == "钟声"
    assert "关键词=钟声" in result.output


def test_careers_limit_option(runner: CliRunner, fake_positions) -> None:
    result = runner.invoke(cli_group, ["--limit", "1"])

    assert result.exit_code == 0, result.output
    assert fake_positions[0]["limit"] == 1
    assert "西湖大学工学院宫先达实验室博士后招聘启事" not in result.output


def test_careers_negative_limit_is_usage_error(runner: CliRunner, fake_positions) -> None:
    result = runner.invoke(cli_group, ["--limit", "-1"])

    assert result.exit_code == 2
    assert "limit" in result.output
    assert fake_positions == []


def test_careers_no_match(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.careers.positions", lambda **kw: [])
    result = runner.invoke(cli_group, ["--keyword", "无"])

    assert result.exit_code == 0
    assert "未找到匹配的岗位" in result.output


def test_careers_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(**kwargs):
        raise ParseError("页面炸了")

    monkeypatch.setattr("westlake_survival.careers.positions", boom)
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 1
    assert "错误：页面炸了" in result.output


def test_careers_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(**kwargs):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.careers.positions", boom)
    result = runner.invoke(cli_group, [])

    assert result.exit_code == 1
    assert "VPN" in result.output


def test_careers_detail_prints_fields(runner: CliRunner, monkeypatch) -> None:
    def fake_fetch(url, **kwargs):
        return PositionDetail(
            title="某课题组招聘启事",
            category="博士后",
            department="生命科学学院",
            address="中国杭州，云谷校区",
            job_type="全职",
            content_html="<p>一、课题组简介</p><p>要求：<b>博士</b>学位。</p>",
            url=url,
        )

    monkeypatch.setattr("westlake_survival.careers.fetch_detail", fake_fetch)
    result = runner.invoke(cli_group, ["detail", "https://www.westlake.edu.cn/x.html"])

    assert result.exit_code == 0, result.output
    assert "标题：某课题组招聘启事" in result.output
    assert "类别：博士后" in result.output
    assert "部门：生命科学学院" in result.output
    assert "地点：中国杭州，云谷校区" in result.output
    assert "一、课题组简介" in result.output
    # HTML 标签被剥掉
    assert "<b>" not in result.output


def test_careers_detail_external_url(runner: CliRunner, monkeypatch) -> None:
    def fake_fetch(url, **kwargs):
        return PositionDetail(title="", url=url)

    monkeypatch.setattr("westlake_survival.careers.fetch_detail", fake_fetch)
    ext = "https://app.mokahr.com/social-recruitment/westlake/43525#/jobs/1"
    result = runner.invoke(cli_group, ["detail", ext])

    assert result.exit_code == 0, result.output
    assert "外部招聘平台" in result.output
    assert ext in result.output


def test_careers_detail_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(url, **kwargs):
        raise ParseError("详情炸了")

    monkeypatch.setattr("westlake_survival.careers.fetch_detail", boom)
    result = runner.invoke(cli_group, ["detail", "https://www.westlake.edu.cn/x.html"])

    assert result.exit_code == 1
    assert "错误：详情炸了" in result.output