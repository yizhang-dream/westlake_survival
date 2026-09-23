"""多源聚合（理学院 / 生科院 / 通识课授课教师）与 ``--source`` 的离线测试。"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from conftest import FakeResponse, FakeSession, multi_source_handler
from westlake_survival.exceptions import ParseError
from westlake_survival.faculty import (
    SOURCES,
    cli_group,
    fetch_detail,
    members,
    parse_science_members,
    parse_sls_members,
    parse_teaching_members,
)


def _session(list_html, science_json, sls_json, teaching_html, *, fail=None):
    return FakeSession(
        multi_source_handler(
            list_html, science_json, sls_json, teaching_html, fail=fail
        )
    )


def _patch(monkeypatch, session):
    from westlake_survival import faculty

    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    return session


# --------------------------------------------------------------------------- #
# 理学院源
# --------------------------------------------------------------------------- #
def test_parse_science_members_dedups_by_url(science_json: str) -> None:
    """fixture 里鲍芳琳重复两条（同 linkUrl），应去重为 5 人。"""
    people = parse_science_members(science_json)
    assert len(people) == 5
    assert [m.name for m in people] == [
        "鲍芳琳",
        "程建军",
        "曹趣",
        "Weronika Czerniawska",
        "王盼",
    ]


def test_parse_science_members_field_mapping(science_json: str) -> None:
    """fullName→name、kexi→subject、remark→lab、workType→work_type、linkUrl→url。"""
    cao = next(m for m in parse_science_members(science_json) if m.name == "曹趣")
    assert cao.school == "理学院"
    assert cao.subject == "物理系"
    assert cao.lab == "量子场论与弦论实验室"
    assert cao.work_type == "主聘"
    assert cao.url == "https://www.westlake.edu.cn/faculty/qu-cao.html"
    assert cao.source == "science"
    assert cao.name_en == ""  # chinesePinyin 不是英文名，不填 name_en


def test_parse_science_members_work_type_values(science_json: str) -> None:
    """workType 1/2/3/4 分别映射为主聘/兼聘/教学/访问。"""
    by_name = {m.name: m for m in parse_science_members(science_json)}
    assert by_name["鲍芳琳"].work_type == "主聘"
    assert by_name["程建军"].work_type == "兼聘"
    assert by_name["Weronika Czerniawska"].work_type == "教学"
    assert by_name["王盼"].work_type == "访问"


def test_parse_science_members_img_url_absolute(science_json: str) -> None:
    """``photograph`` 是本站相对路径，应相对接口地址绝对化。"""
    bao = next(m for m in parse_science_members(science_json) if m.name == "鲍芳琳")
    assert bao.img_url.startswith("https://science.westlake.edu.cn/file/download")


def test_parse_science_members_missing_data_raises() -> None:
    with pytest.raises(ParseError):
        parse_science_members('{"msg": "请求成功"}')
    with pytest.raises(ParseError):
        parse_science_members("不是 JSON")


# --------------------------------------------------------------------------- #
# 生科院源
# --------------------------------------------------------------------------- #
def test_parse_sls_members_count(sls_json: str) -> None:
    assert len(parse_sls_members(sls_json)) == 3


def test_parse_sls_members_field_mapping(sls_json: str) -> None:
    """doctitle→name、en_name→name_en、subject→subject、Subject2→lab、recurl→url。"""
    fang = next(m for m in parse_sls_members(sls_json) if m.name == "方睿博士")
    assert fang.name_en == "Rui Fang, Ph.D."
    assert fang.school == "生命科学学院"
    assert fang.subject == "生物学"
    assert fang.lab == "蛋白质聚集与降解实验室"
    assert fang.url == "https://www.westlake.edu.cn/faculty/rui-fang.html"
    assert fang.source == "sls"
    assert fang.work_type is None


def test_parse_sls_members_joins_subject2_and_subject3(sls_json: str) -> None:
    """Subject2 / Subject3 都非空时用 ``、`` 连接。"""
    xiao = next(m for m in parse_sls_members(sls_json) if m.name == "肖宇晨博士")
    assert xiao.lab == "意识与认知神经科学实验室、认知科学中心"
    # 兼聘学院名原样保留
    assert xiao.school == "生命科学学院与理学院（兼聘）"


def test_parse_sls_members_missing_data_raises() -> None:
    with pytest.raises(ParseError):
        parse_sls_members('{"data": {}}')


# --------------------------------------------------------------------------- #
# 通识课授课教师源
# --------------------------------------------------------------------------- #
def test_parse_teaching_members_count(teaching_html: str) -> None:
    assert len(parse_teaching_members(teaching_html)) == 5


def test_parse_teaching_members_field_mapping(teaching_html: str) -> None:
    """页面无分组字段，school 固定「通识课程」，subject 留空。"""
    karen = next(
        m for m in parse_teaching_members(teaching_html) if m.name == "Karen C. Tan博士"
    )
    assert karen.school == "通识课程"
    assert karen.subject == ""
    assert karen.source == "teaching"
    assert karen.url.endswith("/TeachingFaculty/Karen-Tan.html")


def test_parse_teaching_members_relative_href_made_absolute(
    teaching_html: str,
) -> None:
    """``./202605/t....html`` 应相对授课教师页绝对化。"""
    wang = next(
        m for m in parse_teaching_members(teaching_html) if m.name == "王燕博士"
    )
    assert wang.url == (
        "https://www.westlake.edu.cn/academics/undergraduate_studies/"
        "common_courses/TeachingFaculty/202605/t20260507_66379.html"
    )


def test_parse_teaching_members_empty_page_raises() -> None:
    with pytest.raises(ParseError):
        parse_teaching_members("<html><body>没有教师</body></html>")


# --------------------------------------------------------------------------- #
# 聚合与去重
# --------------------------------------------------------------------------- #
def test_members_aggregates_four_sources(
    monkeypatch, list_html, science_json, sls_json, teaching_html
) -> None:
    _patch(
        monkeypatch, _session(list_html, science_json, sls_json, teaching_html)
    )
    people = members()
    assert {m.source for m in people} == set(SOURCES)
    counts = {name: sum(1 for m in people if m.source == name) for name in SOURCES}
    # main fixture 5 人（含 1 隐藏，默认过滤后 4）；teaching 5 人全在；
    # science 5 人、sls 3 人（fixture 无跨源 url 重叠）
    assert counts == {"main": 4, "science": 5, "sls": 3, "teaching": 5}
    assert len(people) == 17


def test_members_dedup_prefers_main(
    monkeypatch, list_html, sls_json, teaching_html
) -> None:
    """同一 url 在主站与子源都出现时，保留先出现的主站条目。"""
    overlap = json.dumps(
        {
            "msg": "请求成功",
            "data": {
                "outputData": [
                    {
                        "fullName": "李奕璠",
                        "kexi": "2",
                        "workType": "1",
                        "remark": "冷原子量子调控实验室",
                        "linkUrl": "https://www.westlake.edu.cn/faculty/yifan-li.html",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    _patch(
        monkeypatch,
        _session(list_html, overlap, sls_json, teaching_html),
    )
    people = members()
    li = [m for m in people if m.url.endswith("/faculty/yifan-li.html")]
    assert len(li) == 1
    assert li[0].source == "main"


def test_members_source_filter_science(
    monkeypatch, list_html, science_json, sls_json, teaching_html
) -> None:
    _patch(
        monkeypatch, _session(list_html, science_json, sls_json, teaching_html)
    )
    people = members(source="science")
    assert len(people) == 5
    assert all(m.source == "science" for m in people)


def test_members_source_filter_teaching(
    monkeypatch, list_html, science_json, sls_json, teaching_html
) -> None:
    _patch(
        monkeypatch, _session(list_html, science_json, sls_json, teaching_html)
    )
    people = members(source="teaching")
    assert all(m.source == "teaching" for m in people)
    assert any(m.name == "何斌博士" for m in people)


def test_members_unknown_source_raises() -> None:
    with pytest.raises(ValueError):
        members(source="bogus")


def test_members_degrades_when_subsource_fails(
    monkeypatch, list_html, science_json, sls_json, teaching_html
) -> None:
    """理学院源返回 500 时跳过该源，其余三源照常返回（不整体失败）。"""
    _patch(
        monkeypatch,
        _session(
            list_html, science_json, sls_json, teaching_html, fail={"science"}
        ),
    )
    people = members()
    assert not any(m.source == "science" for m in people)
    assert {m.source for m in people} == {"main", "sls", "teaching"}


def test_members_main_failure_still_raises(
    monkeypatch, list_html, science_json, sls_json, teaching_html
) -> None:
    """主站失败不降级：维持既有异常口径（与子源降级不同）。"""
    _patch(
        monkeypatch,
        _session(list_html, science_json, sls_json, teaching_html, fail={"main"}),
    )
    with pytest.raises(ParseError):
        members()


def test_members_science_keyword_search(
    monkeypatch, list_html, science_json, sls_json, teaching_html
) -> None:
    """聚合结果里可按关键词搜到子源教师（曹趣 / 方睿）。"""
    _patch(
        monkeypatch, _session(list_html, science_json, sls_json, teaching_html)
    )
    assert [m.name for m in members(keyword="曹趣")] == ["曹趣"]
    assert [m.name for m in members(keyword="方睿")] == ["方睿博士"]


# --------------------------------------------------------------------------- #
# 无独立主页条目的详情报错
# --------------------------------------------------------------------------- #
def test_fetch_detail_rejects_teaching_page(monkeypatch) -> None:
    """授课教师详情页（非 /faculty/）调用 fetch_detail 抛 ParseError 并说明原因。"""
    session = FakeSession(lambda url, kw: FakeResponse(b"", status=500, url=url))
    monkeypatch.setattr("westlake_survival.faculty.http_session", lambda **kw: session)
    with pytest.raises(ParseError, match="无独立主页"):
        fetch_detail(
            "https://www.westlake.edu.cn/academics/undergraduate_studies/"
            "common_courses/TeachingFaculty/bai-lin.html"
        )
    assert session.calls == []  # 不发请求


# --------------------------------------------------------------------------- #
# CLI --source
# --------------------------------------------------------------------------- #
@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_source_passed_through(runner, monkeypatch) -> None:
    from westlake_survival.faculty import FacultyMember

    seen: list[dict] = []

    def fake(**kw):
        seen.append(kw)
        return [FacultyMember(name="曹趣", school="理学院", source="science")]

    monkeypatch.setattr("westlake_survival.faculty.members", fake)
    result = runner.invoke(cli_group, ["--source", "science"])
    assert result.exit_code == 0, result.output
    assert seen[0]["source"] == "science"
    assert "数据源：science" in result.output


def test_cli_source_all_maps_to_none(runner, monkeypatch) -> None:
    seen: list[dict] = []

    def fake(**kw):
        seen.append(kw)
        return []

    monkeypatch.setattr("westlake_survival.faculty.members", fake)
    result = runner.invoke(cli_group, ["--source", "all"])
    assert result.exit_code == 0, result.output
    assert seen[0]["source"] is None


def test_cli_source_rejects_unknown(runner) -> None:
    result = runner.invoke(cli_group, ["--source", "bogus"])
    assert result.exit_code == 2