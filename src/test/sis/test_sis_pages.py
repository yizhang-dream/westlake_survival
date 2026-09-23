"""``westlake_survival.sis.pages`` 离线测试：登录态抓页、fluid 网格、label-value。

网络层全部打桩（monkeypatch ``pages._session``），不发真实请求。
"""

from __future__ import annotations

import pytest

from westlake_survival.exceptions import ActionError, AuthError, OffCampusError, ParseError
from westlake_survival.sis import pages

from sis_fakes import FakeResponse, FakeSession

PORTAL = "CSPRD_21"


def _fake_session(component_response, *, portal: str = PORTAL) -> FakeSession:
    """构造假 Session：门户根返回带索引的 URL，组件页返回给定响应。"""

    def handler(method: str, url: str, kwargs: dict):
        if "/EMPLOYEE/SA/c/" in url:
            return component_response(url)
        return FakeResponse(
            200,
            text="<html>portal</html>",
            url=f"https://sis.westlake.edu.cn/psc/{portal}/",
        )

    return FakeSession(handler)


# --------------------------------------------------------------------------- #
# fetch_page：门户索引动态化
# --------------------------------------------------------------------------- #
def test_fetch_page_uses_dynamic_portal_index(monkeypatch):
    """组件页 URL 用动态门户索引（此处 CSPRD_21），而不是写死的 CSPRD_3。"""
    seen: list[str] = []

    def handler(method: str, url: str, kwargs: dict):
        seen.append(url)
        return FakeResponse(200, text="<html>ok</html>", url=url)

    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(pages, "_session", lambda: FakeSession(handler))

    html = pages.fetch_page("WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL")

    assert html == "<html>ok</html>"
    assert seen == [
        "https://sis.westlake.edu.cn/psc/CSPRD_21/EMPLOYEE/SA/c/"
        "WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL"
    ]
    assert "CSPRD_3" not in seen[0]


def test_fetch_page_resolves_portal_from_session(monkeypatch):
    """端到端（打桩 _session）：门户根返回 CSPRD_21 时组件页 URL 随之变化。"""
    seen: list[str] = []

    def handler(method: str, url: str, kwargs: dict):
        seen.append(url)
        if "/EMPLOYEE/SA/c/" in url:
            return FakeResponse(200, text="<html>component</html>", url=url)
        return FakeResponse(
            200, text="portal", url=f"https://sis.westlake.edu.cn/psc/{PORTAL}/"
        )

    monkeypatch.setattr(pages, "_session", lambda: FakeSession(handler))
    pages.fetch_page("WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL")

    assert f"/psc/{PORTAL}/" in seen[-1]


def test_portal_index_parsed_from_response_url(monkeypatch):
    """``_portal_index`` 从门户根响应 URL 里解析出 ``CSPRD_21``。"""
    session = FakeSession(
        lambda m, u, k: FakeResponse(
            200, text="x", url=f"https://sis.westlake.edu.cn/psc/{PORTAL}/"
        )
    )
    assert pages._portal_index(session) == PORTAL


def test_portal_index_falls_back_to_default(monkeypatch):
    """门户根响应 URL 无法解析时退回默认索引，不阻断请求。"""
    session = FakeSession(lambda m, u, k: FakeResponse(200, text="x", url="https://x/"))
    assert pages._portal_index(session) == pages.DEFAULT_PORTAL


def test_fetch_page_appends_query(monkeypatch):
    """``query`` 拼成 ``?Page=...``（自动去掉多余前导 ``?``）。"""
    seen: list[str] = []

    def handler(method: str, url: str, kwargs: dict):
        seen.append(url)
        return FakeResponse(200, text="<html/>", url=url)

    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(pages, "_session", lambda: FakeSession(handler))

    pages.fetch_page("WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL", query="Page=WL_EXAM_STU_FL")
    assert seen[0].endswith(
        "WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL?Page=WL_EXAM_STU_FL"
    )


def test_fetch_page_empty_component_raises_value_error():
    with pytest.raises(ValueError):
        pages.fetch_page("")


# --------------------------------------------------------------------------- #
# fetch_page：异常映射
# --------------------------------------------------------------------------- #
def test_fetch_page_login_page_raises_auth_error(monkeypatch, login_page):
    """未登录响应（登录表单 / cmd=login）→ AuthError。"""
    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(
        pages,
        "_session",
        lambda: FakeSession(
            lambda m, u, k: FakeResponse(200, text=login_page, url=u + "?cmd=login")
        ),
    )
    with pytest.raises(AuthError):
        pages.fetch_page("WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL")


def test_fetch_page_unauthorized_raises_action_error(monkeypatch):
    """正文含 ``not authorized`` → ActionError（认证通过但组件未授权）。"""
    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(
        pages,
        "_session",
        lambda: FakeSession(
            lambda m, u, k: FakeResponse(
                200,
                text="<html>You are not authorized to access this component.</html>",
                url=u,
            )
        ),
    )
    with pytest.raises(ActionError) as excinfo:
        pages.fetch_page("WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL")
    assert "not authorized" in str(excinfo.value)


def test_fetch_page_unauthorized_case_insensitive(monkeypatch):
    """``Not Authorized`` 大小写变体同样命中。"""
    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(
        pages,
        "_session",
        lambda: FakeSession(
            lambda m, u, k: FakeResponse(200, text="<p>Not Authorized</p>", url=u)
        ),
    )
    with pytest.raises(ActionError):
        pages.fetch_page("X.Y.GBL")


def test_fetch_page_offcampus_raises_offcampus_error(monkeypatch):
    """403 + 阻断特征 → OffCampusError。"""
    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(
        pages,
        "_session",
        lambda: FakeSession(
            lambda m, u, k: FakeResponse(
                403,
                text="<html>Access forbidden, please contact administrator</html>",
                url=u,
            )
        ),
    )
    with pytest.raises(OffCampusError):
        pages.fetch_page("X.Y.GBL")


def test_fetch_page_offcampus_redirect_raises_offcampus_error(monkeypatch):
    """302 跳向 errorPg=ckreq → OffCampusError。"""
    monkeypatch.setattr(pages, "_portal_index", lambda s: PORTAL)
    monkeypatch.setattr(
        pages,
        "_session",
        lambda: FakeSession(
            lambda m, u, k: FakeResponse(
                302,
                headers={"Location": "https://sis/x?cmd=login&errorPg=ckreq"},
                url=u,
            )
        ),
    )
    with pytest.raises(OffCampusError):
        pages.fetch_page("X.Y.GBL")


# --------------------------------------------------------------------------- #
# parse_fluid_grid：真实脱敏页面
# --------------------------------------------------------------------------- #
def test_parse_fluid_grid_grades_real(grades_real_html: str):
    """真实成绩网格：表头映射 + 7 行数据 + 未出分列为空串。"""
    rows = pages.parse_fluid_grid(grades_real_html, "WL_STU_ENRL_V2")
    assert len(rows) == 7
    assert set(rows[0]) == {"Course Code", "Course Title", "Term", "Grade", "Credits"}
    first = rows[0]
    assert first["Course Code"] == "CST 2000"
    assert first["Grade"] == ""  # 未出分
    assert first["Credits"] == "2.0"
    assert any(r["Grade"] == "P" for r in rows)


def test_parse_fluid_grid_exams_real(exams_real_html: str):
    """真实考试网格：从两张同 id 表中选中数据表，4 行全空排期列。"""
    rows = pages.parse_fluid_grid(exams_real_html, "WL_EXAM_STU_VW")
    assert len(rows) == 4
    assert rows[0]["Course Code"] == "PHY 1004"
    assert rows[0]["Course Title"] == "General Physics Laboratory Ⅱ"
    assert set(rows[0]) == {
        "Course Code",
        "Course Title",
        "Date",
        "Time",
        "Type",
        "Method",
        "Venue",
        "Seat Nbr",
    }
    # 行号列（空表头）与按钮列不应出现为键。
    assert "" not in rows[0]


def test_parse_fluid_grid_splits_br_cells(synth_fluid_grid_html: str):
    """单元格 ``<br />``（含模板真实换行）拆成 ``\\n`` 分隔的多值。"""
    rows = pages.parse_fluid_grid(synth_fluid_grid_html, "SYNTH_GRID")
    assert len(rows) == 2
    assert rows[0]["Date"] == "2026/09/03 - 2026/12/24\n2027/02/20 - 2027/06/10"
    assert rows[0]["Time"] == "Thurs 13:30 To 15:05\nMon 08:00 To 09:35"


def test_parse_fluid_grid_empty_cells_are_empty_strings(synth_fluid_grid_html: str):
    """``&nbsp;`` 空单元格归一为空串（不留 ``&nbsp;`` 字面量）。"""
    rows = pages.parse_fluid_grid(synth_fluid_grid_html, "SYNTH_GRID")
    assert rows[1]["Date"] == ""
    assert rows[1]["Time"] == ""


def test_parse_fluid_grid_missing_grid_raises_parse_error(grades_real_html: str):
    with pytest.raises(ParseError) as excinfo:
        pages.parse_fluid_grid(grades_real_html, "NOT_A_GRID")
    assert "NOT_A_GRID" in str(excinfo.value)


def test_parse_fluid_grid_empty_table_returns_empty_list():
    """网格存在但无数据行、有表头 → 返回空列表（不抛错）。"""
    html = (
        "<div id='EMPTY_GRID$grid$0'>"
        "<table><thead><tr><th>Course Code</th><th>Term</th></tr></thead>"
        "<tbody class='ps_grid-body'></tbody></table></div>"
    )
    assert pages.parse_fluid_grid(html, "EMPTY_GRID") == []


def test_parse_fluid_grid_duplicate_header_keeps_first():
    """重复表头取先出现者（同 :func:`parser._map_columns` 语义）。"""
    html = (
        "<table id='DUP_GRID'><tr><th>Course Code</th><th>Course Code</th><th>Term</th></tr>"
        "<tr><td>A</td><td>B</td><td>T</td></tr></table>"
    )
    rows = pages.parse_fluid_grid(html, "DUP_GRID")
    assert rows == [{"Course Code": "A", "Term": "T"}]


def test_parse_fluid_grid_no_header_raises_parse_error():
    html = "<table id='NOHDR_GRID'><tr><td>x</td></tr></table>"
    with pytest.raises(ParseError):
        pages.parse_fluid_grid(html, "NOHDR_GRID")


# --------------------------------------------------------------------------- #
# parse_label_values
# --------------------------------------------------------------------------- #
def test_parse_label_values_pairs(label_value_html: str):
    """标签-值配对；空标签 / 空值 / 无值标签不产出。"""
    pairs = pages.parse_label_values(label_value_html)
    assert pairs == {
        "Student ID": "***",
        "Name": "***",
        "Program": "Test Program",
        "Address": "Line 1 Line 2",
    }
    assert "Advisor" not in pairs  # 值为空
    assert "" not in pairs  # 空标签不产出


def test_parse_label_values_empty_html():
    assert pages.parse_label_values("") == {}
    assert pages.parse_label_values("<html><body>无字段</body></html>") == {}


def test_parse_label_values_br_multi_line():
    """label-value 里的 ``<br />`` 折叠为单空格（标签值整体保持单行）。"""
    html = (
        "<div class='ps_box-edit'><div class='ps_box-label'><span class='ps-label'>X</span></div>"
        "<span class='ps_box-value'>A<br />B</span></div>"
    )
    assert pages.parse_label_values(html) == {"X": "A B"}


def test_parse_label_values_nested_value_text():
    """值容器内再嵌一层元素时，文本上浮仍能取到。"""
    html = (
        "<div class='ps_box-edit'><div class='ps_box-label'>"
        "<span class='ps-label'>K</span></div>"
        "<div class='ps_box-value'><span>V</span></div></div>"
    )
    assert pages.parse_label_values(html) == {"K": "V"}


def test_parse_label_values_void_tags_do_not_break_stack():
    """``<img>`` 等空元素不入栈，后续标签仍正确配对。"""
    html = (
        "<div><div class='ps_box-label'><span class='ps-label'>L</span></div>"
        "<div class='ps_box-value'><img src='x.png'>Z</div></div>"
    )
    assert pages.parse_label_values(html) == {"L": "Z"}


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def test_pages_public_exports():
    import westlake_survival.sis.pages as p

    for name in ("fetch_page", "parse_fluid_grid", "parse_label_values"):
        assert callable(getattr(p, name))
