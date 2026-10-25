"""学业导师 / 其他申请两个新块的端到端解析（离线，结构最小的页面快照）。

覆盖 2026-10-25 新接入的两条链路：

- ``advisor.advising``：公告 + 轮次下拉框 + 两轮名单（切轮次靠 POST）；
- ``applications.other_applications``：学籍异动 tab 列表 + 三类空状态提示。

运行：``pytest src/test/sis/test_sis_new_blocks_e2e.py -q``
"""

from __future__ import annotations

import pytest

from westlake_survival.sis import pages
from westlake_survival.sis.advisor import advising
from westlake_survival.sis.applications import other_applications


class _Response:
    def __init__(self, text: str, url: str = "") -> None:
        self.text = text
        self.status_code = 200
        self.url = url
        self.final_url = url


def _advisor_page(rows: list[tuple[str, str, str, str, str]], *, rotation: str) -> str:
    """最小导师页：win3 表单 + 轮次下拉 + 公告 + 名单网格。"""
    selected = "selected='selected'" if rotation == "10" else ""
    other = "" if rotation == "10" else "selected='selected'"
    body = "".join(
        "<tr class='ps_grid-row' id='WL_ADV_CHOOSE_V$0_row_{i}'>"
        "<td class='ps_num'>{i}</td><td>{name}</td><td>{gender}</td>"
        "<td>{school}</td><td>{quota}</td><td>{first}</td></tr>".format(
            i=index, name=name, gender=gender, school=school, quota=quota, first=first
        )
        for index, (name, gender, school, quota, first) in enumerate(rows)
    )
    return f"""
<form name='win3' method='post' action='https://sis.example/EMPLOYEE/SA/c/WL_CUSTOMIZE_MENU.WL_ADV_CHOOSE_COM.GBL'>
<input name='ICStateNum' value='7'>
<select id='WL_ADV_CHSE_WRK_WL_ADV_ROT'><option value=""> </option>
<option value="10" {selected}>1st Rotation</option>
<option value="20" {other}>2nd Rotation</option></select>
<span class='ps_box-value' id='WL_ADV_CHSE_WRK_DESCR254' >The results have been announced: 张三 (San ZHANG).</span>
<table class='ps_grid-flex-head'><thead><tr class='ps_grid-head-row'>
<th class='ps_grid-col psc_num ptgrid-rownumber' scope='col'><div class='ps_box_grid-col'> </div></th>
<th>Name</th><th>Gender</th><th>School</th><th>Quota</th><th>1st Choice</th></tr></thead>
<tbody class='ps_grid-body'>{body}</tbody></table>
</form>
"""


class _AdvisorSession:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def get(self, url: str, **_kwargs) -> _Response:
        if "WL_ADV_CHOOSE_COM" in url:
            return _Response(
                _advisor_page(
                    [("张三 (San ZHANG)", "Male", "School of Science", "2", "5"),
                     ("李四 (Si LI)", "Female", "School of Engineering", "1", "0")],
                    rotation="10",
                ),
                url,
            )
        return _Response("", url)  # 门户索引探测

    def post(self, url: str, data=None, **_kwargs) -> _Response:
        self.posts.append(dict(data or {}))
        return _Response(
            _advisor_page(
                [("张三 (San ZHANG)", "Male", "School of Science", "2", "0")],
                rotation="20",
            ),
            url,
        )


@pytest.fixture
def advisor_session(monkeypatch):
    session = _AdvisorSession()
    monkeypatch.setattr(pages, "_session", lambda: session)
    return session


def test_advising_two_rotations(advisor_session) -> None:
    """公告、轮次切换、两轮名单与志愿计数都解析出来。"""
    info = advising()

    assert info.assigned == "张三 (San ZHANG)"
    assert [rotation.label for rotation in info.rotations] == ["1st Rotation", "2nd Rotation"]
    assert [len(rotation.advisors) for rotation in info.rotations] == [2, 1]

    first = info.rotations[0].advisors[0]
    assert first.name == "张三 (San ZHANG)"
    assert first.school == "School of Science"
    assert first.quota == "2"
    assert first.choices["1st Choice"] == "5"
    assert info.rotations[1].advisors[0].remaining == ""

    # 切第二轮：ICAction 与下拉值都要带上
    assert advisor_session.posts, "应有一次轮次切换 POST"
    assert advisor_session.posts[0]["ICAction"] == "WL_ADV_CHSE_WRK_WL_ADV_ROT"
    assert advisor_session.posts[0]["WL_ADV_CHSE_WRK_WL_ADV_ROT"] == "20"
    assert advisor_session.posts[0]["ICStateNum"] == "7"


class _ApplicationsSession:
    def get(self, url: str, **_kwargs) -> _Response:
        if "WL_PRGCHG_CEN_COM" in url:
            return _Response(
                "<a class='ps_tab-link' id='pagetab_0'>Major Selection</a>"
                "<a class='ps_tab-link' id='pagetab_1'>Change of Major</a>"
                "<a class='ps_tab-link' id='pagetab_2'>Suspension of Study</a>",
                url,
            )
        if "WL_CREATE_KNSQ_COM" in url:
            return _Response("<div>My Applications</div><div>The current query has no results.</div>", url)
        if "WL_ADM_APPL_LIST" in url:
            return _Response("<div>Your Applications</div><div>You have not applied for any programs.</div>", url)
        if "WL_SA_OBTA_TILE_FL" in url:
            return _Response("<div>Not Open</div>", url)
        if "WL_SA_ACAD_PRG_FL" in url:
            return _Response(
                "<div>The academic advisement has not been released, please wait patiently</div>",
                url,
            )
        return _Response("", url)


@pytest.fixture
def applications_session(monkeypatch):
    monkeypatch.setattr(pages, "_session", lambda: _ApplicationsSession())


def test_other_applications_statuses(applications_session) -> None:
    """学籍异动 tab 列表 + 三类空状态提示。"""
    data = other_applications()

    assert data.status_change.tabs == ["Major Selection", "Change of Major", "Suspension of Study"]
    assert data.difficulty.count == 0
    assert "no results" in data.difficulty.message
    assert "not applied" in data.phd.message.lower()
    assert data.employment.message == "Not Open"
    assert "not been released" in data.academic_progress.message
    assert data.to_dict()["status_change"]["tabs"][1] == "Change of Major"
