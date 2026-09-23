"""``westlake_survival.faculty`` 的离线解析测试（网络层打桩）。"""

from __future__ import annotations

import pytest

from conftest import FakeResponse, FakeSession
from westlake_survival.exceptions import ParseError
from westlake_survival.faculty import (
    BASE_URL,
    LIST_URL,
    FacultyMember,
    FacultyRepresentative,
    _split_subject,
    parse_detail,
    parse_members,
    school_options,
    subject_options,
)


# --------------------------------------------------------------------------- #
# subject 拆分
# --------------------------------------------------------------------------- #
def test_split_subject_normal() -> None:
    assert _split_subject("物理学</br>冷原子量子调控实验室") == (
        "物理学",
        "冷原子量子调控实验室",
    )


def test_split_subject_leading_empty() -> None:
    """实测有 14 人只写了实验室，首段为空。"""
    assert _split_subject("</br>早期宇宙实验室") == ("", "早期宇宙实验室")


def test_split_subject_no_br_returns_none_lab() -> None:
    assert _split_subject("物理学") == ("物理学", None)


def test_split_subject_plain_br_variant() -> None:
    assert _split_subject("物理学<br>量子物态扫描针探实验室") == (
        "物理学",
        "量子物态扫描针探实验室",
    )


def test_split_subject_multiple_segments_joined() -> None:
    """多段（实测 5 人）用 ``、`` 连接。"""
    assert _split_subject(
        "化学</br>太阳能燃料与太阳能电池实验室<br>人工光合作用与太阳能燃料中心"
    ) == ("化学", "太阳能燃料与太阳能电池实验室、人工光合作用与太阳能燃料中心")


def test_split_subject_self_closing_br() -> None:
    assert _split_subject("数学<br/>随机分析") == ("数学", "随机分析")


def test_split_subject_empty() -> None:
    assert _split_subject("") == ("", None)


# --------------------------------------------------------------------------- #
# 列表解析
# --------------------------------------------------------------------------- #
def test_parse_members_count(list_html: str) -> None:
    people = parse_members(list_html)
    assert len(people) == 5


def test_parse_members_fields(list_html: str) -> None:
    first = parse_members(list_html)[0]
    assert first.name == "李奕璠博士"
    assert first.school == "理学院"
    assert first.subject == "物理学"
    assert first.lab == "冷原子量子调控实验室"
    assert first.url == "https://www.westlake.edu.cn/faculty/yifan-li.html"
    assert first.visible is True


def test_parse_members_relative_url_made_absolute(list_html: str) -> None:
    """``/faculty/juen-zhang.html`` 应绝对化到站点根。"""
    zhang = next(m for m in parse_members(list_html) if m.name == "张举恩博士")
    assert zhang.url == "https://www.westlake.edu.cn/faculty/juen-zhang.html"


def test_parse_members_multi_segment_subject(list_html: str) -> None:
    """多段 ``<br>``（实测 5 人）拆出的实验室用 ``、`` 连接。"""
    zhang = next(m for m in parse_members(list_html) if m.name == "张举恩博士")
    assert zhang.subject == "生物学"
    assert zhang.lab == "大脑与身体交互实验室、人工光合作用与太阳能燃料中心"


def test_parse_members_img_url_made_absolute(list_html: str) -> None:
    """``./science/...`` 应相对列表页绝对化。"""
    first = parse_members(list_html)[0]
    assert first.img_url.startswith("https://www.westlake.edu.cn/about/faculty/science/")
    assert first.img_url.endswith("W020260611362809332339.jpg")


def test_parse_members_hidden_flag_preserved(list_html: str) -> None:
    hidden = next(m for m in parse_members(list_html) if m.name == "张举恩博士")
    assert hidden.visible is False


def test_parse_members_empty_memberlist_raises() -> None:
    html = 'new faculty("#app", {memberList: [], mounted: function () {} });'
    with pytest.raises(ParseError):
        parse_members(html)


def test_parse_members_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_members("<html><body>没有组件</body></html>")


def test_parse_members_handles_function_callback(list_html: str) -> None:
    """组件块尾部有 ``mounted: function () {}``，解析不应受影响。"""
    assert len(parse_members(list_html)) == 5


def test_parse_members_deduplicates_same_url() -> None:
    """官网 memberList 实测会重复收录同一教师（同 url），应按 url 去重。"""
    html = (
        'new faculty("#app", {memberList: ['
        '{name: "曾文锋博士", nameEn: "Wen-Feng Zeng, Ph.D.", school: "工学院", '
        'url: "https://www.westlake.edu.cn/faculty/wenfeng-zeng.html", show: true},'
        '{name: "曾文锋博士", nameEn: "Wen-Feng Zeng, Ph.D.", school: "工学院", '
        'url: "https://www.westlake.edu.cn/faculty/wenfeng-zeng.html", show: true},'
        '{name: "李奕璠博士", school: "理学院", '
        'url: "https://www.westlake.edu.cn/faculty/yifan-li.html", show: true}'
        "], mounted: function () {} });"
    )
    people = parse_members(html)
    assert [m.name for m in people] == ["曾文锋博士", "李奕璠博士"]


def test_parse_members_keeps_empty_url_entries() -> None:
    """url 为空的条目无法判定同一人，一律保留。"""
    html = (
        'new faculty("#app", {memberList: ['
        '{name: "甲博士", url: "", show: true},'
        '{name: "乙博士", url: "", show: true}'
        "], mounted: function () {} });"
    )
    assert len(parse_members(html)) == 2


# --------------------------------------------------------------------------- #
# 枚举选项
# --------------------------------------------------------------------------- #
def test_school_options(list_html: str) -> None:
    assert school_options(list_html) == ["理学院", "工学院", "生命科学学院", "医学院"]


def test_subject_options(list_html: str) -> None:
    assert subject_options(list_html) == ["材料科学与工程", "物理学"]


# --------------------------------------------------------------------------- #
# 详情解析
# --------------------------------------------------------------------------- #
def test_parse_detail_fields(detail_html: str) -> None:
    detail = parse_detail(detail_html, url="https://www.westlake.edu.cn/faculty/yifan-li.html")
    assert detail.name == "李奕璠博士"
    assert detail.title == "理学院"
    assert detail.email == "liyifan@westlake.edu.cn"
    assert detail.url == "https://www.westlake.edu.cn/faculty/yifan-li.html"


def test_parse_detail_strips_trailing_comma(detail_html: str) -> None:
    """详情页 ``subject`` 实测为 ``"物理学,"``，应去掉尾部逗号。"""
    assert parse_detail(detail_html).subject == "物理学"


def test_parse_detail_lab(detail_html: str) -> None:
    assert parse_detail(detail_html).lab == "冷原子量子调控实验室"


def test_parse_detail_rich_text_unescaped(detail_html: str) -> None:
    r"""``<\/p>`` 转义应还原成 ``</p>``，且内容为完整 HTML 字符串。"""
    detail = parse_detail(detail_html)
    assert detail.biography_html.startswith("<div class=")
    assert "</p>" in detail.biography_html
    assert "李奕璠" in detail.biography_html
    assert "清华大学，博士" in detail.history_html
    assert "量子精密测量" in detail.research_html


def test_parse_detail_missing_component_raises() -> None:
    with pytest.raises(ParseError):
        parse_detail("<html></html>")


# --------------------------------------------------------------------------- #
# 代表作 representativeList
# --------------------------------------------------------------------------- #
def test_parse_detail_representatives_fields(detail_html: str) -> None:
    """fixture 的 representativeList 为 2 项，各含 title / content。"""
    reps = parse_detail(detail_html).representatives
    assert len(reps) == 2
    assert all(isinstance(r, FacultyRepresentative) for r in reps)
    assert reps[0].title == "代表论文"
    assert reps[1].title == "联系我们"
    assert reps[0].content_html.startswith('<div class="view TRS_UEDITOR')
    assert "</p>" in reps[0].content_html


def test_representative_lines_split_paper_list(detail_html: str) -> None:
    """论文 content 里逐条一个 <p>（[1] / [2]），lines() 应拆成两条纯文本。"""
    paper = parse_detail(detail_html).representatives[0]
    lines = paper.lines()
    assert len(lines) == 2
    assert lines[0].startswith("[1] ")
    assert lines[1].startswith("[2] ")
    # 标签被剥掉，但内容保留
    assert "<" not in " ".join(lines)
    assert "A representative paper title" in lines[0]
    assert "Phys. Rev. Lett." in lines[1]


def test_representative_lines_strips_tags_and_keeps_text(detail_html: str) -> None:
    contact = parse_detail(detail_html).representatives[1]
    lines = contact.lines()
    assert lines[0] == "电子邮箱：***@westlake.edu.cn"
    assert "课题组长期招收博士研究生。" in lines


def test_representatives_empty_list() -> None:
    """representativeList 为空数组时退化为空列表，不影响其余字段。"""
    html = (
        'new facultyDetail("#app", {personObj: {name: "X", post: "P"}, '
        'biographyStr: "", historyStr: "", researchStr: "", '
        "representativeList: [], mounted: function () {} });"
    )
    detail = parse_detail(html)
    assert detail.representatives == []
    assert detail.name == "X"


def test_representatives_missing_key_returns_empty() -> None:
    """键缺失（页面结构变化）时静默降级为空列表，其余字段照常解析。"""
    html = (
        'new facultyDetail("#app", {personObj: {name: "X", post: "P"}, '
        'biographyStr: "", historyStr: "", researchStr: "", '
        "mounted: function () {} });"
    )
    detail = parse_detail(html)
    assert detail.representatives == []
    assert detail.title == "P"


def test_representatives_skips_non_dict_items() -> None:
    """数组里混入非对象元素时应跳过，不抛异常。"""
    html = (
        'new facultyDetail("#app", {personObj: {name: "X"}, '
        'biographyStr: "", historyStr: "", researchStr: "", '
        'representativeList: ["坏条目", {title: "代表论文", content: "<p>[1] A</p>"}], '
        "mounted: function () {} });"
    )
    reps = parse_detail(html).representatives
    assert len(reps) == 1
    assert reps[0].title == "代表论文"
    assert reps[0].lines() == ["[1] A"]


def test_representative_lines_empty_content() -> None:
    """content 为空串时 lines() 返回空列表（「联系我们」实测可为空）。"""
    assert FacultyRepresentative(title="联系我们", content_html="").lines() == []


# --------------------------------------------------------------------------- #
# matches()
# --------------------------------------------------------------------------- #
def test_member_matches_keyword_fields() -> None:
    m = FacultyMember(
        name="李奕璠博士",
        name_en="Yifan Li, Ph.D.",
        school="理学院",
        subject="物理学",
        lab="冷原子量子调控实验室",
    )
    assert m.matches("李奕璠")
    assert m.matches("yifan")  # 不区分大小写
    assert m.matches("物理")
    assert m.matches("冷原子")
    assert not m.matches("化学")


# --------------------------------------------------------------------------- #
# members() 过滤（网络打桩）
# --------------------------------------------------------------------------- #
def _patch(monkeypatch, list_html: str):
    """让 ``faculty.members`` 用注入的假 Session 拿固定列表页。"""
    from westlake_survival import faculty

    session = FakeSession(lambda url, kw: FakeResponse(list_html, url=url))
    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    return session


def test_members_filters_hidden_by_default(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    names = [m.name for m in faculty.members()]
    assert "张举恩博士" not in names
    assert len(names) == 4


def test_members_include_hidden(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    names = [m.name for m in faculty.members(include_hidden=True)]
    assert "张举恩博士" in names
    assert len(names) == 5


def test_members_filter_school(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    people = faculty.members(school="医学院")
    # 张举恩（医学院，隐藏）被默认过滤，只剩兼聘的林文斌
    assert [m.name for m in people] == ["林文斌博士"]


def test_members_filter_school_includes_dual_appointment(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    # 林文斌是"理学院与工学院与医学院（兼聘）"，三院筛选都应命中
    for school in ("理学院", "工学院", "医学院"):
        assert any(m.name == "林文斌博士" for m in faculty.members(school=school))


def test_members_filter_keyword(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    assert [m.name for m in faculty.members(keyword="量子物质理论")] == ["纪文杰博士"]


def test_members_filter_keyword_name_en(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    assert [m.name for m in faculty.members(keyword="wenbin")] == ["林文斌博士"]


def test_members_limit(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    assert len(faculty.members(limit=2)) == 2


def test_members_limit_zero(monkeypatch, list_html: str) -> None:
    from westlake_survival import faculty

    _patch(monkeypatch, list_html)
    assert faculty.members(limit=0) == []


def test_members_uses_list_url_and_decodes_content(monkeypatch, list_html: str) -> None:
    """确认走的是 ``response.content`` UTF-8 解码（latin-1 乱码也还原）。"""
    from westlake_survival import faculty

    session = _patch(monkeypatch, list_html)
    people = faculty.members(limit=1)
    assert people[0].name == "李奕璠博士"
    url, kw = session.calls[0]
    assert url == LIST_URL


# --------------------------------------------------------------------------- #
# 异常映射
# --------------------------------------------------------------------------- #
def test_members_maps_timeout_to_westlake_error(monkeypatch) -> None:
    import requests

    from westlake_survival import faculty
    from westlake_survival.exceptions import WestlakeError

    def boom(url, kw):
        raise requests.Timeout("超时")

    monkeypatch.setattr(faculty, "http_session", lambda **kw: FakeSession(boom))
    with pytest.raises(WestlakeError):
        faculty.members()


def test_members_maps_404_to_not_found(monkeypatch) -> None:
    from westlake_survival import faculty
    from westlake_survival.exceptions import NotFound

    session = FakeSession(lambda url, kw: FakeResponse(b"", status=404, url=url))
    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    with pytest.raises(NotFound):
        faculty.members()


def test_members_maps_500_to_parse_error(monkeypatch) -> None:
    from westlake_survival import faculty
    from westlake_survival.exceptions import ParseError

    session = FakeSession(lambda url, kw: FakeResponse(b"", status=500, url=url))
    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    with pytest.raises(ParseError):
        faculty.members()


def test_members_maps_offcampus_403(monkeypatch) -> None:
    """403 且正文命中阻断特征 → OffCampusError。"""
    from westlake_survival import faculty
    from westlake_survival.exceptions import OffCampusError

    body = b"Access forbidden, please contact administrator"
    session = FakeSession(lambda url, kw: FakeResponse(body, status=403, url=url))
    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    with pytest.raises(OffCampusError):
        faculty.members()


def test_members_plain_403_is_parse_error(monkeypatch) -> None:
    """403 但正文无阻断特征 → 按 ParseError 处理（不误判校外）。"""
    from westlake_survival import faculty
    from westlake_survival.exceptions import ParseError

    session = FakeSession(lambda url, kw: FakeResponse(b"nope", status=403, url=url))
    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    with pytest.raises(ParseError):
        faculty.members()


def test_fetch_detail_relative_url_absolute(monkeypatch, detail_html: str) -> None:
    from westlake_survival import faculty

    session = FakeSession(lambda url, kw: FakeResponse(detail_html, url=url))
    monkeypatch.setattr(faculty, "http_session", lambda **kw: session)
    detail = faculty.fetch_detail("/faculty/yifan-li.html")
    assert session.calls[0][0] == BASE_URL + "faculty/yifan-li.html"
    assert detail.name == "李奕璠博士"