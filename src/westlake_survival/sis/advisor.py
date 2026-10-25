"""SIS 学业导师（Academic Advisor）页读取层。

入口（2026-10-25 登录态实测）
============================
首页「Academic Advisor」瓦片 → ``WL_CUSTOMIZE_MENU.WL_ADV_CHOOSE_COM.GBL``。
**不在左侧导航的「学术建议」目录里**（那里是培养方案/学术进度，且当前未发布），
又是一个「瓦片直达、导航无叶项」的页面。

页面结构
========
- 公告：``id='WL_ADV_CHSE_WRK_DESCR254'``，形如
  ``The results have been announced: 某导师 (Name).``（分配结果）；
- 轮次下拉框：``WL_ADV_CHSE_WRK_WL_ADV_ROT``（``10`` = 1st Rotation，
  ``20`` = 2nd Rotation），切换靠 ``ICAction`` 同名动作 POST；
- 名单网格：``WL_ADV_CHOOSE_V``。列随轮次变化——
  第一轮 ``Name / Gender / Country/Region / School / Quota / 1st…7th Choice``，
  第二轮多 ``Remaining Quota``、志愿只到 ``5th Choice``。

列名兜底
========
不同轮次列不一致，故数据模型只固化 ``name/gender/country/school/quota/
remaining`` 六个稳定字段，其余 ``*Choice`` 原样进 ``choices`` 字典（键为
页面表头），轮次增减志愿不丢数据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from westlake_survival.exceptions import ParseError
from westlake_survival.sis import pages
from westlake_survival.sis.pages import parse_fluid_grid

__all__ = [
    "ADVISOR_COMPONENT",
    "ADVISOR_GRID_ID",
    "Advisor",
    "AdvisorRotation",
    "AdvisorInfo",
    "advising",
]

#: 导师选择页组件。
ADVISOR_COMPONENT = "WL_CUSTOMIZE_MENU.WL_ADV_CHOOSE_COM.GBL"

#: 名单网格 id。
ADVISOR_GRID_ID = "WL_ADV_CHOOSE_V"

#: 轮次下拉框的字段 id 与动作名（同一个）。
ROTATION_FIELD = "WL_ADV_CHSE_WRK_WL_ADV_ROT"

#: 分配结果公告的字段 id。
ANNOUNCE_FIELD = "WL_ADV_CHSE_WRK_DESCR254"

_ANNOUNCE_RE = re.compile(
    rf"id='{ANNOUNCE_FIELD}'[^>]*>\s*([^<]+?)\s*</span>"
)

_SELECT_RE = re.compile(
    r"<select id='" + ROTATION_FIELD + r"'.*?</select>", re.S
)
_OPTION_RE = re.compile(
    r"<option value=(['\"])(.*?)\1([^>]*)>([^<]*)</option>"
)

#: 志愿列：``1st Choice`` / ``7th Choice`` …
_CHOICE_RE = re.compile(r"^\d+(?:st|nd|rd|th) Choice$")

#: 公告里「已公布」的结果：``…announced: 某某 (Name).``
_ASSIGNED_RE = re.compile(r"announced:\s*(.+?)[.。]?\s*$")


@dataclass
class Advisor:
    """一位导师在第一/二轮的配额与志愿人次。"""

    name: str = ""
    gender: str = ""
    country: str = ""
    school: str = ""
    quota: str = ""
    remaining: str = ""
    choices: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "gender": self.gender,
            "country": self.country,
            "school": self.school,
            "quota": self.quota,
            "remaining": self.remaining,
            "choices": dict(self.choices),
        }

    @classmethod
    def from_row(cls, row: dict) -> "Advisor":
        choices = {k: v for k, v in row.items() if _CHOICE_RE.match(str(k))}
        return cls(
            name=str(row.get("Name") or "").strip(),
            gender=str(row.get("Gender") or "").strip(),
            country=str(row.get("Country/Region") or "").strip(),
            school=str(row.get("School") or "").strip(),
            quota=str(row.get("Quota") or "").strip(),
            remaining=str(row.get("Remaining Quota") or "").strip(),
            choices=choices,
        )


@dataclass
class AdvisorRotation:
    """一个轮次的导师名单。"""

    code: str = ""
    label: str = ""
    advisors: list[Advisor] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "count": len(self.advisors),
            "advisors": [advisor.to_dict() for advisor in self.advisors],
        }


@dataclass
class AdvisorInfo:
    """导师选择页全量：公告 + 各轮名单。"""

    announcement: str = ""
    assigned: str = ""
    rotations: list[AdvisorRotation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "announcement": self.announcement,
            "assigned": self.assigned,
            "rotations": [rotation.to_dict() for rotation in self.rotations],
        }


def _announcement(html: str) -> tuple[str, str]:
    """取分配公告与其中的导师名。"""
    match = _ANNOUNCE_RE.search(html or "")
    if not match:
        return "", ""
    text = re.sub(r"\s+", " ", match.group(1)).strip()
    assigned = _ASSIGNED_RE.search(text)
    return text, (assigned.group(1).strip() if assigned else "")


def _rotation_options(html: str) -> list[tuple[str, str, bool]]:
    """取轮次下拉框：``[(value, label, selected)]``（忽略空值项）。"""
    select = _SELECT_RE.search(html or "")
    if not select:
        return []
    options = []
    for _, value, attrs, label in _OPTION_RE.findall(select.group(0)):
        label = label.strip()
        if not value or not label:
            continue
        options.append((value, label, "selected" in attrs))
    return options


def _advisors(html: str) -> list[Advisor]:
    rows = parse_fluid_grid(html, ADVISOR_GRID_ID)
    return [Advisor.from_row(row) for row in rows]


def advising() -> AdvisorInfo:
    """取学业导师页：分配公告 + 各轮次名单。

    首次 GET 拿当前轮次；其余轮次按下拉框选项逐个 POST（回填表单状态）。

    Raises:
        OffCampusError: 校外访问被拒。
        AuthError: 会话失效。
        ActionError: 组件对当前角色未授权。
        ParseError: 页面结构变化（找不到名单网格等）。
    """
    session = pages._session()
    html = pages.fetch_page(ADVISOR_COMPONENT)
    announcement, assigned = _announcement(html)

    options = _rotation_options(html)
    if not options:  # 下拉框缺失：至少返回当前页
        options = [("", "", True)]

    action, fields = pages.form_state(html)
    info = AdvisorInfo(announcement=announcement, assigned=assigned)
    page_html = html
    for value, label, selected in options:
        if not selected:
            data = dict(fields)
            data[ROTATION_FIELD] = value
            data["ICAction"] = ROTATION_FIELD
            response = session.post(action, data=data, timeout=60, allow_redirects=True)
            page_html = pages._extract_page(response, ADVISOR_COMPONENT)
            action, fields = pages.form_state(page_html)
        info.rotations.append(
            AdvisorRotation(code=value, label=label, advisors=_advisors(page_html))
        )
    if not info.rotations:
        raise ParseError("导师页没有任何轮次名单，页面结构可能已变化。")
    return info
