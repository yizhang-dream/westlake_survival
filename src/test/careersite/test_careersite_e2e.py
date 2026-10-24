"""就业服务网模块端到端测试：解析器（离线样例固化）→ 真实首页 → CLI/页面。

离线用例默认跑（内嵌 2026-10-24 实测形态样例）；在线用例 ``-m live``。
"""

from __future__ import annotations

import pytest

from westlake_survival.careersite import CAREER_SITE_BASE, CareerItem, _parse_home

SAMPLE = """
<li class="newsline"><div class="cont content-txt"><span class="line-time"><p>19</p>
<p>2026.10</p></span><a class="title" target="_blank" title="华为ICT BG 云核心网产品2027届应届生招聘"
href="/campus/view/id/1129108">华为ICT BG 云核心网产品2027届应届生招聘</a></div></li>
<li class="newsline"><div class="cont content-txt"><span class="line-time"><p>17</p>
<p>2026.10</p></span><a class="title" target="_blank" title="长沙“星斗”工程向你发出邀请函"
href="/campus/view/id/1129114">长沙“星斗”工程向你发出邀请函</a></div></li>
<ul><li><div class="cont"><div class="line-time"><p>23</p><p>2026.10</p></div>
<div class="content-info"><p class="text-box"><a href="/jobfair/view/id/56807" target="_blank"
class="title"><span class="status-text status-yijuban">已举办</span>西湖大学2026年博士生、博士后秋季就业洽谈会邀请函</a>
<span class="time">13:30-16:00</span></p><p class="icon-box">
<span class="address">杭州市西湖区墩余路600号西湖大学（云谷校区）理学楼南侧亲水平台</span>
<span class="browse"><i class="iconfont icon-liulancishu"></i>25</span></p></div></div></li></ul>
<ul><li><div class="cont"><div class="line-time"><p>21</p><p>2026.09</p></div>
<div class="content-info"><p class="text-box"><a href="/teachin/view/id/208443" target="_blank"
class="title">华为要来我校云谷校区做专场宣讲啦！</a>
<span style="color: #dedede; text-shadow:0.5px 0.5px 0.5px #dedede;padding-left:7px;float:left;">已举办</span>
<span class="time">13:50-15:00</span></p><p class="icon-box">
<span class="address"><i class="iconfont icon-address_icon-copy"></i>西湖大学云谷校区E10楼</span>
<span class="browse"><i class="iconfont icon-liulancishu"></i>5</span></p></div></div></li></ul>
"""


# --------------------------------------------------------------------------- #
# 离线：解析器形态固化
# --------------------------------------------------------------------------- #
def test_parse_home_three_kinds_offline() -> None:
    items = _parse_home(SAMPLE)
    assert len(items) == 4  # campus×2 + jobfair + teachin
    by_kind: dict[str, object] = {}
    for i in items:  # 每类取第一条
        by_kind.setdefault(i.kind, i)
    assert set(by_kind) == {"campus", "jobfair", "teachin"}

    campus = by_kind["campus"]
    assert campus.item_id == "1129108"
    assert campus.date == "2026.10.19"
    assert campus.url == f"{CAREER_SITE_BASE}/campus/view/id/1129108"
    assert campus.kind_label == "招聘公告"

    fair = by_kind["jobfair"]
    # 陷阱回归：招聘会的状态 span 嵌在 <a> 内部，标题不得混入「已举办」
    assert fair.title.startswith("西湖大学2026年博士生")
    assert fair.status == "已举办"
    assert fair.time == "13:30-16:00"
    assert "理学楼南侧亲水平台" in fair.venue
    assert fair.views == "25"

    session = by_kind["teachin"]
    # 宣讲会的状态是内联样式 span（无 status-text 类），也要能识别
    assert session.status == "已举办"
    assert session.venue == "西湖大学云谷校区E10楼"
    assert session.kind_label == "宣讲会"


def test_career_item_to_dict_offline() -> None:
    item = CareerItem(kind="jobfair", title="t")
    payload = item.to_dict()
    assert payload["kind_label"] == "招聘会"
    assert payload["url"] == ""


def test_mcp_tool_registered() -> None:
    from westlake_survival.mcp_server import list_tools

    names = {spec["name"] for spec in list_tools()}
    assert "career_latest" in names


# --------------------------------------------------------------------------- #
# 在线：真实首页 / CLI / WebUI
# --------------------------------------------------------------------------- #
@pytest.mark.live
def test_live_homepage_three_sections() -> None:
    from westlake_survival.careersite import announcements

    items = announcements()
    kinds = {i.kind for i in items}
    assert "campus" in kinds  # 招聘公告常年有
    assert all(i.url.startswith(CAREER_SITE_BASE) for i in items)
    assert all(i.date for i in items)
    # 过滤路径
    only_fairs = announcements("jobfair")
    assert all(i.kind == "jobfair" for i in only_fairs)


@pytest.mark.live
def test_live_cli_career_list() -> None:
    from click.testing import CliRunner

    from westlake_survival.careersite import cli_group

    result = CliRunner().invoke(cli_group, ["list"])
    assert result.exit_code == 0
    assert "https://career.westlake.edu.cn/" in result.output


@pytest.mark.live
def test_live_webui_careers_page_has_site_section() -> None:
    from westlake_survival.webui.app import create_app

    page = create_app().test_client().get("/careers")
    assert page.status_code == 200
    assert "就业服务网".encode() in page.data
    assert "career.westlake.edu.cn".encode() in page.data
