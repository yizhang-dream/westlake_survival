"""``westlake probe`` 命令测试（各项 monkeypatch 离线）。"""

from __future__ import annotations

from westlake_survival.cli import main as main_mod
from westlake_survival.exceptions import ActionError


def test_probe_sis_cart_not_authorized_via_exception(monkeypatch) -> None:
    """fetch_page 抛「not authorized」ActionError → 「选课窗口未开」。"""
    import westlake_survival.sis.pages as pages

    def boom(component, **_kw):
        raise ActionError("SIS 组件页未授权（正文含 'not authorized'）：xxx")

    monkeypatch.setattr(pages, "fetch_page", boom)
    status, detail = main_mod._probe_sis_cart()
    assert status == "选课窗口未开"
    assert "not authorized" in detail


def test_probe_sis_cart_not_authorized_in_body(monkeypatch) -> None:
    """正文含 not authorized → 「选课窗口未开」。"""
    import westlake_survival.sis.pages as pages

    monkeypatch.setattr(
        pages, "fetch_page", lambda component, **kw: "<p>You are not authorized</p>"
    )
    status, _ = main_mod._probe_sis_cart()
    assert status == "选课窗口未开"


def test_probe_sis_cart_authorized(monkeypatch) -> None:
    """正文无 not authorized → 「已授权（可开发选课功能！）」。"""
    import westlake_survival.sis.pages as pages

    monkeypatch.setattr(pages, "fetch_page", lambda component, **kw: "<html>Shopping Cart</html>")
    status, _ = main_mod._probe_sis_cart()
    assert status == "已授权（可开发选课功能！）"


def test_probe_opac_404(monkeypatch) -> None:
    """OPAC 返回 404 → 「仍未恢复」。"""
    from westlake_survival import _net

    class FakeResponse:
        status_code = 404

    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(_net, "http_session", lambda **kw: FakeSession())
    status, detail = main_mod._probe_opac()
    assert status == "HTTP 404"
    assert "仍未恢复" in detail


def test_probe_pms_reachable(monkeypatch) -> None:
    """打印匿名接口 code=0 → 「可达」，并报告网点数。"""
    from westlake_survival import _net

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"code": 0, "message": "", "result": [{"dwDevSN": 1}, {"dwDevSN": 2}]}

    class FakeSession:
        def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(_net, "http_session", lambda **kw: FakeSession())
    status, detail = main_mod._probe_pms()
    assert status == "可达"
    assert "2 个网点" in detail


def test_probe_canvas_token_configured(monkeypatch) -> None:
    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "tok")
    status, _ = main_mod._probe_canvas_token()
    assert status == "已配置"


def test_probe_canvas_token_missing(monkeypatch) -> None:
    monkeypatch.delenv("WESTLAKE_CANVAS_TOKEN", raising=False)
    import westlake_survival.canvas as canvas_pkg

    monkeypatch.setattr(canvas_pkg, "resolve_token", lambda *a, **k: None)
    status, detail = main_mod._probe_canvas_token()
    assert status == "未配置"
    assert "WESTLAKE_CANVAS_TOKEN" in detail


def test_probe_item_failure_does_not_raise() -> None:
    """单项探测函数抛异常时收敛为「失败」，不向外抛。"""
    def boom():
        raise RuntimeError("单项炸了")

    status, detail = main_mod._run_probe_item(boom)
    assert status == "失败"
    assert "单项炸了" in detail


def test_probe_table_renders_all_items_and_degrades(runner, cli_group, monkeypatch) -> None:
    """probe 命令：四项都出现在表格里；某项失败只让该行失败，命令仍 exit 0。"""

    def boom():
        raise RuntimeError("不可达")

    items = (
        ("SIS 选课组件授权", lambda: ("选课窗口未开", "正文含 not authorized")),
        ("OPAC 端点", lambda: ("HTTP 404", "仍未恢复（服务端 404）")),
        ("打印系统匿名接口", boom),
        ("Canvas token", lambda: ("未配置", "设置环境变量")),
    )
    monkeypatch.setattr(main_mod, "PROBE_ITEMS", items)
    result = runner.invoke(cli_group, ["probe"])
    assert result.exit_code == 0, result.output
    assert "SIS 选课组件授权" in result.output
    assert "OPAC 端点" in result.output
    assert "HTTP 404" in result.output
    assert "失败" in result.output
    assert "不可达" in result.output
    assert "Canvas token" in result.output
