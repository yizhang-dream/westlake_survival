"""第二课堂成绩单的端到端解析：用真实页面快照驱动完整入口链。

离线：``pages._session`` 换成假会话，按 URL / ``ICAction`` 返回采集自真实
SIS 的脱敏快照（``fixtures/second_class/``，2026-10-25）。覆盖：

- 瓦片页 ``LaunchURL`` → 主组件页的入口链；
- 5 个维度各一次 ``POST ICAction=WL_SEC_EMP_WRK_DESCR100$N``；
- h3 分节 / h4 二级要求 / fluid 网格行与百分比解析；
- 空网格（团队合作下的两个「任选其一」）不产行、不报错。

运行：``pytest src/test/sis/test_second_class_e2e.py -q``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.sis import pages
from westlake_survival.sis.second_class import second_classroom

FIXTURES = Path(__file__).parent / "fixtures" / "second_class"


class _Response:
    """最小响应对象：``pages._extract_page`` 只读 status/text/url。"""

    def __init__(self, text: str, url: str = "") -> None:
        self.text = text
        self.status_code = 200
        self.url = url
        self.final_url = url


class _FakeSIS:
    """假会话：门户根 → 瓦片页 → 主页面；POST 按维度序号回对应快照。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def get(self, url: str, **_kwargs) -> _Response:
        self.calls.append(("GET", url))
        if "WL_SEC_WEL_TILE_FL" in url:
            return _Response(self._fixture("tile.html"), url)
        if "/psc/CSPRD_" in url and "WL_SEC_EMPL_CLS_CM" not in url:
            # 门户索引探测：final_url 里带 CSPRD_x
            return _Response("", url)
        return _Response(self._fixture("report_0.html"), url)

    def post(self, url: str, data=None, **_kwargs) -> _Response:
        action = str((data or {}).get("ICAction", ""))
        self.calls.append(("POST", action))
        index = int(action.rsplit("$", 1)[-1])
        return _Response(self._fixture(f"report_{index}.html"), url)


@pytest.fixture
def fake_session(monkeypatch):
    session = _FakeSIS()
    monkeypatch.setattr(pages, "_session", lambda: session)
    return session


def test_second_classroom_report(fake_session) -> None:
    """5 个维度、分节/二级要求/进度全部解析出来。"""
    report = second_classroom()

    assert [category.name for category in report.categories] == [
        "Responsibility and Practice",
        "Academic Studies and Research",
        "Sports and Health",
        "Humanities and Arts",
        "Teamwork and Collaboration",
    ]
    assert [category.percent for category in report.categories] == [39, 29, 31, 8, 0]

    # 责任与实践：3 个分节，劳动教育下还有 2 个二级要求
    practice = report.categories[0]
    assert [node.name for node in practice.nodes] == [
        "Social Practice",
        "Volunteer Service",
        "Labor Activities",
    ]
    social, volunteer, labor = practice.nodes
    assert social.rows[0].requirement == "14-Day Social Practice"
    assert (social.rows[0].percent, social.rows[0].done, social.rows[0].total) == (0, "0", "14")
    assert social.rows[0].unit == "Day(s)"

    assert volunteer.rows[0].requirement == "48-Hour Volunteer Service"
    assert (volunteer.rows[0].percent, volunteer.rows[0].done, volunteer.rows[0].total) == (
        50, "24", "48",
    )

    assert [child.name for child in labor.children] == [
        "Public Area Duty",
        "Dorm Cleanliness Inspection",
    ]
    duty, dorm = labor.children
    assert len(duty.rows) == 6
    assert duty.rows[0].requirement == "2025-2026 Fall Term"
    assert duty.rows[0].percent == 100
    assert dorm.rows[0].percent == 100
    assert dorm.rows[0].done == "12"

    # 单要求维度
    assert report.categories[1].nodes[0].rows[0].requirement == "24 Activities"
    assert report.categories[1].nodes[0].rows[0].done == "7"
    assert report.categories[2].nodes[0].rows[0].total == "480"
    assert report.categories[3].nodes[0].rows[0].total == "12"

    # 团队合作：三个「任选其一」，各自一条 0% 要求
    teamwork = report.categories[4]
    assert [node.name for node in teamwork.nodes] == [
        "Student Leader",
        "Activity Organizer",
        "Competition or Project",
    ]
    assert all(node.note.startswith("(Complete either") for node in teamwork.nodes)
    assert all(node.rows[0].percent == 0 for node in teamwork.nodes)

    # 未完成要求：社会实践 1 + 志愿 1 + 公共区域值日 4 + 学术/体育/人文各 1 + 团队 3
    assert report.pending == 12


def test_second_classroom_to_dict(fake_session) -> None:
    """``to_dict`` 给出稳定结构（页面/模板/MCP 共用）。"""
    payload = second_classroom().to_dict()
    assert payload["count"] == 5
    assert payload["pending"] == 12
    first = payload["categories"][0]
    assert first["name"] == "Responsibility and Practice"
    assert first["percent"] == 39
    assert first["nodes"][2]["children"][0]["rows"][0]["percent"] == 100


def test_second_classroom_entry_chain(fake_session) -> None:
    """入口链：门户探测 → 瓦片页 → 主页面 → 4 次维度切换。"""
    second_classroom()
    kinds = [kind for kind, _ in fake_session.calls]
    actions = [value for kind, value in fake_session.calls if kind == "POST"]
    assert kinds.count("POST") == 4
    assert actions == [f"WL_SEC_EMP_WRK_DESCR100${index}" for index in (1, 2, 3, 4)]
