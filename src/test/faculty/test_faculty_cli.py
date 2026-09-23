"""``westlake faculty`` 命令组测试（离线，网络层打桩）。"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.exceptions import OffCampusError, ParseError
from westlake_survival.faculty import (
    FacultyDetail,
    FacultyMember,
    FacultyRepresentative,
    cli_group,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _people() -> list[FacultyMember]:
    return [
        FacultyMember(
            name="李奕璠博士",
            school="理学院",
            subject="物理学",
            lab="冷原子量子调控实验室",
            url="https://www.westlake.edu.cn/faculty/yifan-li.html",
        ),
        FacultyMember(
            name="张举恩博士",
            school="医学院",
            subject="生物学",
            lab="大脑与身体交互实验室",
            url="https://www.westlake.edu.cn/faculty/juen-zhang.html",
        ),
    ]


@pytest.fixture
def fake_members(monkeypatch):
    """打桩 ``faculty.members``，记录调用参数。"""
    calls: list[dict] = []

    def fake(school=None, keyword=None, include_hidden=False, limit=None, **kw):
        calls.append(
            {
                "school": school,
                "keyword": keyword,
                "include_hidden": include_hidden,
                "limit": limit,
            }
        )
        return _people()

    monkeypatch.setattr("westlake_survival.faculty.members", fake)
    return calls


def test_cli_group_importable() -> None:
    assert cli_group.name == "faculty"


def test_faculty_lists_table(runner: CliRunner, fake_members) -> None:
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0, result.output
    assert "共 2 人" in result.output
    assert "李奕璠博士" in result.output
    assert "冷原子量子调控实验室" in result.output
    assert fake_members[0]["include_hidden"] is False
    # CLI 取全量后在展示层截断，传给库函数的 limit 恒为 None
    assert fake_members[0]["limit"] is None


def test_faculty_passes_filters(runner: CliRunner, fake_members) -> None:
    result = runner.invoke(
        cli_group, ["--school", "医学院", "--keyword", "脑", "--limit", "5", "--all"]
    )
    assert result.exit_code == 0, result.output
    call = fake_members[0]
    assert call == {
        "school": "医学院",
        "keyword": "脑",
        "include_hidden": True,
        "limit": None,
    }
    assert "学院：医学院" in result.output


def test_faculty_truncation_hint(runner: CliRunner, monkeypatch) -> None:
    """结果多于 --limit 时打印「共 N 条，已显示 M 条」提示。"""
    people = [
        FacultyMember(name=f"教师{i}", school="理学院", url=f"https://x/{i}")
        for i in range(30)
    ]
    monkeypatch.setattr("westlake_survival.faculty.members", lambda **kw: people)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0, result.output
    assert "共 30 条，已显示 20 条" in result.output
    assert "教师19" in result.output
    assert "教师20" not in result.output


def test_faculty_no_hint_when_not_truncated(runner: CliRunner, fake_members) -> None:
    """结果不超过 --limit 时不出现截断提示。"""
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 0, result.output
    assert "已显示" not in result.output


def test_faculty_rejects_unknown_school(runner: CliRunner) -> None:
    result = runner.invoke(cli_group, ["--school", "不存在学院"])
    assert result.exit_code == 2


def test_faculty_no_match(runner: CliRunner, monkeypatch) -> None:
    monkeypatch.setattr("westlake_survival.faculty.members", lambda **kw: [])
    result = runner.invoke(cli_group, ["--keyword", "无"])
    assert result.exit_code == 0
    assert "未找到匹配的教师" in result.output


def test_faculty_error_exit_code(runner: CliRunner, monkeypatch) -> None:
    def boom(**kw):
        raise ParseError("页面炸了")

    monkeypatch.setattr("westlake_survival.faculty.members", boom)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 1
    assert "错误：页面炸了" in result.output


def test_faculty_offcampus_hint(runner: CliRunner, monkeypatch) -> None:
    def boom(**kw):
        raise OffCampusError("被拦了")

    monkeypatch.setattr("westlake_survival.faculty.members", boom)
    result = runner.invoke(cli_group, [])
    assert result.exit_code == 1
    assert "VPN" in result.output


def test_faculty_detail_command(runner: CliRunner, monkeypatch) -> None:
    # 教师真名/邮箱一律脱敏为 ***（隐私铁律）。
    detail = FacultyDetail(
        name="***博士",
        title="理学院",
        subject="物理学",
        lab="冷原子量子调控实验室",
        email="***@westlake.edu.cn",
        url="https://www.westlake.edu.cn/faculty/***.html",
        representatives=[
            FacultyRepresentative(
                title="代表论文",
                content_html="<p>[1] ***, A paper, <strong>Science</strong> 391 (2026).</p>",
            ),
            FacultyRepresentative(
                title="联系我们",
                content_html="<p>电子邮箱：***@westlake.edu.cn</p>",
            ),
        ],
    )
    seen: list[str] = []

    def fake(url, **kw):
        seen.append(url)
        return detail

    monkeypatch.setattr("westlake_survival.faculty.fetch_detail", fake)
    url = "https://www.westlake.edu.cn/faculty/***.html"
    result = runner.invoke(cli_group, ["detail", url])
    assert result.exit_code == 0, result.output
    assert "***博士" in result.output
    assert "***@westlake.edu.cn" in result.output
    # 代表作条数与列表项
    assert "代表作：2 项" in result.output
    assert "代表论文：" in result.output
    assert "联系我们：" in result.output
    assert "[1] ***, A paper, Science 391 (2026)." in result.output
    assert "电子邮箱：***@westlake.edu.cn" in result.output
    assert seen == [url]


def test_faculty_detail_command_no_representatives(runner: CliRunner, monkeypatch) -> None:
    """无代表作时仍打印「代表作：0 项」，不出现区块标题。"""
    detail = FacultyDetail(name="***博士", url="https://x")
    monkeypatch.setattr("westlake_survival.faculty.fetch_detail", lambda url, **kw: detail)
    result = runner.invoke(cli_group, ["detail", "https://x"])
    assert result.exit_code == 0, result.output
    assert "代表作：0 项" in result.output


def test_faculty_detail_command_truncates_long_representative(
    runner: CliRunner, monkeypatch
) -> None:
    """超过预览行数时只列前 5 行并报总数。"""
    lines = "".join(f"<p>[{i}] paper {i}</p>" for i in range(1, 9))
    detail = FacultyDetail(
        name="***博士",
        url="https://x",
        representatives=[FacultyRepresentative(title="代表论文", content_html=lines)],
    )
    monkeypatch.setattr("westlake_survival.faculty.fetch_detail", lambda url, **kw: detail)
    result = runner.invoke(cli_group, ["detail", "https://x"])
    assert result.exit_code == 0, result.output
    assert "[1] paper 1" in result.output
    assert "[5] paper 5" in result.output
    assert "[6] paper 6" not in result.output
    assert "…（共 8 条）" in result.output


def test_faculty_detail_error(runner: CliRunner, monkeypatch) -> None:
    def boom(url, **kw):
        raise ParseError("详情页炸了")

    monkeypatch.setattr("westlake_survival.faculty.fetch_detail", boom)
    result = runner.invoke(cli_group, ["detail", "https://x"])
    assert result.exit_code == 1
    assert "错误：详情页炸了" in result.output