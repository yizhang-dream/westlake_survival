"""sis.client 离线测试：登录页检测、导出探测、缓存。"""

from __future__ import annotations

import json

import pytest

from westlake_survival._cache import cache_path
from westlake_survival.exceptions import ActionError, AuthError, OffCampusError
from westlake_survival.sis.client import (
    SCHEDULE_CACHE_NAME,
    SISClient,
    _find_export_action,
    get_schedule,
    reset_sis,
)

from sis_fakes import FakeResponse, FakeSession


# --------------------------------------------------------------------------- #
# fetch_schedule_html：登录页 / 校外检测
# --------------------------------------------------------------------------- #
def test_fetch_html_happy_path(schedule_grid_html):
    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    client = SISClient(session=session)
    html = client.fetch_schedule_html()
    assert "计算机程序设计" in html
    assert session.calls[0][0] == "GET"


def test_fetch_html_login_page_raises_auth_error(login_page):
    session = FakeSession(
        lambda m, u, k: FakeResponse(
            200, text=login_page, url="https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login"
        )
    )
    client = SISClient(session=session)
    with pytest.raises(AuthError):
        client.fetch_schedule_html()


def test_fetch_html_ckreq_url_raises_auth_error(schedule_grid_html):
    session = FakeSession(
        lambda m, u, k: FakeResponse(
            200,
            text=schedule_grid_html,
            url="https://sis.westlake.edu.cn/psc/CSPRD_3/?cmd=login&errorPg=ckreq",
        )
    )
    client = SISClient(session=session)
    with pytest.raises(AuthError):
        client.fetch_schedule_html()


def test_normal_page_with_logout_link_not_treated_as_login(schedule_grid_html):
    """正常课表页里出现 cmd=login（退出链接）不应误判为未登录。"""
    page = schedule_grid_html.replace(
        "</body>", '<a href="/psc/CSPRD_3/?cmd=logout">退出</a></body>'
    )
    session = FakeSession(
        lambda m, u, k: FakeResponse(200, text=page, url=u)
    )
    client = SISClient(session=session)
    html = client.fetch_schedule_html()
    assert "计算机程序设计" in html


def test_fetch_html_offcampus_raises():
    session = FakeSession(
        lambda m, u, k: FakeResponse(
            403, text="Access forbidden, please contact administrator", url=u
        )
    )
    client = SISClient(session=session)
    with pytest.raises(OffCampusError):
        client.fetch_schedule_html()


# --------------------------------------------------------------------------- #
# 导出动作探测
# --------------------------------------------------------------------------- #
def test_find_export_action_icaction():
    html = '<a href="javascript:submitAction_win0(document.win0,'
    html += "'SSR_SSR-wide_BT_DOWNLOAD$0')\" "
    html += 'ICAction=SSR_SSR-wide_BT_DOWNLOAD$0 id="DL">下载</a>'
    action = _find_export_action(html)
    assert action is not None
    assert action["ICAction"].startswith("SSR_SSR")


def test_find_export_action_submit_action():
    html = (
        '<a href="javascript:submitAction_win0(document.win0,'
        "'SSR_MD_SP_FL_EXPORT$0')" + '">导出</a>'
    )
    action = _find_export_action(html)
    assert action == {"ICAction": "SSR_MD_SP_FL_EXPORT$0"}


def test_find_export_action_download_word_context():
    html = '<button title="下载 Excel" onclick="doit(\'ICAction=SSR_DL_GRID\')">x</button>'
    action = _find_export_action(html)
    assert action == {"ICAction": "SSR_DL_GRID"}


def test_find_export_action_none_when_absent():
    assert _find_export_action("<html><body>没有下载按钮</body></html>") is None
    assert _find_export_action("") is None


def test_export_xls_missing_action_raises_with_snippet(schedule_grid_html):
    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    client = SISClient(session=session)
    with pytest.raises(ActionError) as excinfo:
        client.export_schedule_xls()
    message = str(excinfo.value)
    assert "未找到导出入口" in message
    assert "页面片段" in message


def test_export_xls_happy_path_returns_bytes(ps_xls_bytes):
    page = (
        '<html><body><a href="javascript:submitAction_win0('
        "document.win0,'SSR_SSR-wide_BT_DOWNLOAD$0')\">下载</a></body></html>"
    )

    def handler(method, url, kw):
        if method == "GET":
            return FakeResponse(200, text=page, url=url)
        return FakeResponse(200, text="", url=url, content=ps_xls_bytes)

    session = FakeSession(handler)
    client = SISClient(session=session)
    content = client.export_schedule_xls()
    assert content == ps_xls_bytes
    assert session.calls[-1][0] == "POST"


# --------------------------------------------------------------------------- #
# get_schedule：缓存
# --------------------------------------------------------------------------- #
def test_get_schedule_parses_and_caches(schedule_grid_html):
    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    client = SISClient(session=session)
    sessions = client.get_schedule()
    assert {s.course_code for s in sessions} == {"CS101", "PHY200"}

    cached = json.loads(cache_path(SCHEDULE_CACHE_NAME).read_text(encoding="utf-8"))
    assert len(cached) == 2
    assert cached[0]["course_code"] in {"CS101", "PHY200"}


def test_get_schedule_uses_cache_without_refetch(schedule_grid_html):
    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    client = SISClient(session=session)
    client.get_schedule()
    calls_after_first = len(session.calls)

    second = client.get_schedule()  # 命中缓存，不再发请求
    assert len(session.calls) == calls_after_first
    assert {s.course_code for s in second} == {"CS101", "PHY200"}


def test_get_schedule_refresh_refetches(schedule_grid_html):
    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    client = SISClient(session=session)
    client.get_schedule()
    calls_after_first = len(session.calls)
    client.get_schedule(refresh=True)
    assert len(session.calls) > calls_after_first


def test_get_schedule_bad_source_raises(schedule_grid_html):
    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    client = SISClient(session=session)
    with pytest.raises(ValueError):
        client.get_schedule(source="pdf")


def test_get_schedule_xls_source(ps_xls_bytes):
    page = (
        '<a href="javascript:submitAction_win0('
        "document.win0,'SSR_SSR-wide_BT_DOWNLOAD$0')\">下载</a>"
    )

    def handler(method, url, kw):
        if method == "GET":
            return FakeResponse(200, text=page, url=url)
        return FakeResponse(200, text="", url=url, content=ps_xls_bytes)

    session = FakeSession(handler)
    client = SISClient(session=session)
    sessions = client.get_schedule(source="xls")
    assert {s.course_code for s in sessions} == {
        "CS101",
        "PHY200",
        "EST2005",
        "SEM101",
        "PE100",
    }


def test_module_level_get_schedule_uses_singleton(monkeypatch, schedule_grid_html):
    import westlake_survival.sis.client as client_mod

    session = FakeSession(lambda m, u, k: FakeResponse(200, text=schedule_grid_html, url=u))
    monkeypatch.setattr(client_mod, "_singleton", SISClient(session=session))
    sessions = get_schedule()
    assert sessions
    reset_sis()