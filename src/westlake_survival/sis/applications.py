"""SIS 其余学生申请类页面：学籍异动 / 困难认定 / 本博衔接 / 就业。

这些页面都来自首页瓦片（导航目录里没有对应叶项），且当前学生账号下
**基本无数据**；本模块只做「有没有、多少条、什么提示」的状态汇总，供
学业页把「后端存在但暂时为空」的能力也展示出来，避免看起来像没接。

各页实测（2026-10-25）
=====================
- 学籍异动 ``WL_CUSTOMIZE_MENU.WL_PRGCHG_CEN_COM.GBL``：6 个 tab
  （Major Selection / Deferred Registration / Change of Major /
  Change of Supervisor / Suspension of Study / Resumption of Study），
  均为表单入口，无既有申请记录。
- 困难认定 ``WL_CUSTOMIZE_MENU.WL_CREATE_KNSQ_COM.GBL``：标题
  「My Applications」，正文「The current query has no results.」。
- 本博衔接 ``WL_CUSTOMIZE_MENU.WL_ADM_APPL_LIST.GBL``：标题
  「Your Applications」，正文「You have not applied for any programs.」。
- 就业 ``WL_SA_MENU.WL_SA_OBTA_TILE_FL.GBL``：正文「Not Open」（服务未开放）。
- 学术进度 ``WL_CUSTOMIZE_MENU.WL_SA_ACAD_PRG_FL.GBL``：提示
  「The academic advisement has not been released, please wait patiently」。
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

from westlake_survival.sis import pages

__all__ = [
    "STATUS_CHANGE_COMPONENT",
    "DIFFICULTY_COMPONENT",
    "PHD_COMPONENT",
    "EMPLOYMENT_COMPONENT",
    "EMPLOYMENT_QUERY",
    "PROGRESS_COMPONENT",
    "PROGRESS_QUERY",
    "ApplicationStatus",
    "OtherApplications",
    "other_applications",
]

#: 学籍异动（转专业 / 休复学 / 导师变更等）组件。
STATUS_CHANGE_COMPONENT = "WL_CUSTOMIZE_MENU.WL_PRGCHG_CEN_COM.GBL"

#: 困难认定组件。
DIFFICULTY_COMPONENT = "WL_CUSTOMIZE_MENU.WL_CREATE_KNSQ_COM.GBL"

#: 本博衔接申请组件。
PHD_COMPONENT = "WL_CUSTOMIZE_MENU.WL_ADM_APPL_LIST.GBL"

#: 就业起始页组件与查询串。
EMPLOYMENT_COMPONENT = "WL_SA_MENU.WL_SA_OBTA_TILE_FL.GBL"
EMPLOYMENT_QUERY = "Page=WL_SA_OBTA_TILE_FL&pStart=WL_SA_OBTA_CM_GBL"

#: 学术进度（培养方案完成度）组件与查询串；当前账号提示「尚未发布」。
PROGRESS_COMPONENT = "WL_CUSTOMIZE_MENU.WL_SA_ACAD_PRG_FL.GBL"
PROGRESS_QUERY = "page=WL_SA_ACAD_PRG_FL"

#: 页面 tab（学籍异动的 6 类业务）。
_TAB_RE = re.compile(r"class='ps_tab-link'[^>]*>([^<]+)</a>")

#: fluid 网格数据行 id：``GID$N_row_M``。
_ROW_RE = re.compile(r"id='[A-Z0-9_]+\$\d+_row_\d+'")

#: 已知「空 / 未开放」提示语（按优先级匹配正文行）。
_EMPTY_HINTS = (
    "no results",
    "not applied",
    "not open",
    "not been released",
    "no data",
    "no records",
    "you have not",
    "currently no",
)

_SCRIPT_RE = re.compile(r"<script.*?</script>", re.S | re.I)
_STYLE_RE = re.compile(r"<style.*?</style>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ApplicationStatus:
    """一类申请的状态：条目数 + 页面提示语。"""

    count: int = 0
    message: str = ""
    tabs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"count": self.count, "message": self.message, "tabs": list(self.tabs)}


@dataclass
class OtherApplications:
    """其余申请类页面的汇总。"""

    status_change: ApplicationStatus = field(default_factory=ApplicationStatus)
    difficulty: ApplicationStatus = field(default_factory=ApplicationStatus)
    phd: ApplicationStatus = field(default_factory=ApplicationStatus)
    employment: ApplicationStatus = field(default_factory=ApplicationStatus)
    academic_progress: ApplicationStatus = field(default_factory=ApplicationStatus)

    def to_dict(self) -> dict:
        return {
            "status_change": self.status_change.to_dict(),
            "difficulty": self.difficulty.to_dict(),
            "phd": self.phd.to_dict(),
            "employment": self.employment.to_dict(),
            "academic_progress": self.academic_progress.to_dict(),
        }


def _visible_lines(html: str) -> list[str]:
    """页面可见文本行（去脚本/样式/标签）。"""
    text = _STYLE_RE.sub("", _SCRIPT_RE.sub("", html or ""))
    text = _TAG_RE.sub("\n", _html.unescape(text))
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]


def _status(html: str) -> ApplicationStatus:
    """从页面推断条目数与提示语。"""
    lines = _visible_lines(html)
    message = ""
    for line in lines:
        lowered = line.lower()
        if any(hint in lowered for hint in _EMPTY_HINTS):
            message = line
            break
    return ApplicationStatus(count=len(_ROW_RE.findall(html or "")), message=message)


def other_applications() -> OtherApplications:
    """汇总学籍异动 / 困难认定 / 本博衔接 / 就业四类页面状态。

    Raises:
        OffCampusError: 校外访问被拒。
        AuthError: 会话失效。
        ActionError: 某组件对当前角色未授权。
    """
    status_html = pages.fetch_page(STATUS_CHANGE_COMPONENT)
    tabs: list[str] = []
    for name in _TAB_RE.findall(status_html):
        name = name.strip()
        if name and name not in tabs:
            tabs.append(name)

    # 四类空状态页互不依赖，并行抓（与 /sis 其它块同款做法）
    from concurrent.futures import ThreadPoolExecutor

    targets = (
        (DIFFICULTY_COMPONENT, ""),
        (PHD_COMPONENT, ""),
        (EMPLOYMENT_COMPONENT, EMPLOYMENT_QUERY),
        (PROGRESS_COMPONENT, PROGRESS_QUERY),
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        difficulty, phd, employment, progress = pool.map(
            lambda item: _status(pages.fetch_page(item[0], query=item[1])),
            targets,
        )

    return OtherApplications(
        status_change=ApplicationStatus(count=len(_ROW_RE.findall(status_html)), tabs=tabs),
        difficulty=difficulty,
        phd=phd,
        employment=employment,
        academic_progress=progress,
    )
