"""scholar SSO 三级通道端到端测试：cookie jar 回环 / 决策链 / 安全探针。

离线用例（默认跑）：jar 读写、合并去重、ensure 三级决策逻辑（注入探针）。
在线用例（``-m live``）：只读探测（verifyCodeIsNeed）与会话状态——
**不做任何 authExecute 提交**（验证码态下试错会给失败计数续期）。
"""

from __future__ import annotations

import json

import pytest

from westlake_survival import scholar
from westlake_survival.scholar import (
    CaptchaRequired,
    COOKIES_PATH,
    _merge_cookie_jar,
    _save_cookie_jar,
    _load_cookie_session,
    sso_ensure,
)


class _FakeCookie:
    def __init__(self, name, value, domain):
        self.name, self.value, self.domain = name, value, domain
        self.path, self.expires = "/", None


def test_cookie_jar_roundtrip_offline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(scholar, "COOKIES_PATH", tmp_path / "cookies.json")
    fake = type("S", (), {"cookies": [_FakeCookie("_idp_session", "V1", "idp.westlake.edu.cn"),
                                      _FakeCookie("sid", "S1", "fsso.cnki.net")]})()
    assert _save_cookie_jar(fake) == 2
    session, loaded = _load_cookie_session()
    assert loaded == 2
    # 合并去重：同名同域覆盖，不重复
    _merge_cookie_jar([{"name": "_idp_session", "value": "V2",
                        "domain": "idp.westlake.edu.cn", "path": "/", "expires": -1}])
    jar = json.loads((tmp_path / "cookies.json").read_text(encoding="utf-8"))["cookies"]
    idp = [c for c in jar if c["name"] == "_idp_session"]
    assert len(idp) == 1 and idp[0]["value"] == "V2"


def test_ensure_prefers_live_session_offline(monkeypatch) -> None:
    """会话仍活：直接复用，不探验证码、不登录。"""
    monkeypatch.setattr(scholar, "sso_alive",
                        lambda target="cnki": {"logged_in": True, "final_url": "https://fsso.cnki.net/x",
                                               "cookies_loaded": 3, "detail": "ok"})
    called = {"captcha": 0, "login": 0}
    monkeypatch.setattr(scholar, "iam_captcha_required", lambda *a, **k: called.__setitem__("captcha", 1))
    monkeypatch.setattr(scholar, "carsi_login_requests", lambda *a, **k: called.__setitem__("login", 1))
    result = sso_ensure("cnki", allow_browser=False)
    assert result["path"] == "session" and called == {"captcha": 0, "login": 0}


def test_ensure_requests_when_captcha_off_offline(monkeypatch) -> None:
    """会话失效 + 验证码关：走无头 requests 登录（零人工）。"""
    monkeypatch.setattr(scholar, "sso_alive",
                        lambda target="cnki": {"logged_in": False, "final_url": "", "detail": "dead"})
    monkeypatch.setattr(scholar, "iam_captcha_required", lambda *a, **k: False)
    monkeypatch.setattr(scholar, "carsi_login_requests",
                        lambda *a, **k: {"final_url": "https://fsso.cnki.net/secure/x", "cookies_saved": 5})
    result = sso_ensure("cnki", allow_browser=False)
    assert result["path"] == "requests" and result["cookies_saved"] == 5


def test_ensure_captcha_blocks_headless_offline(monkeypatch) -> None:
    """会话失效 + 验证码开 + 不许弹浏览器：明确报 CaptchaRequired，绝不提交登录。"""
    monkeypatch.setattr(scholar, "sso_alive",
                        lambda target="cnki": {"logged_in": False, "final_url": "", "detail": "dead"})
    monkeypatch.setattr(scholar, "iam_captcha_required", lambda *a, **k: True)
    with pytest.raises(CaptchaRequired):
        sso_ensure("cnki", allow_browser=False)


# --------------------------------------------------------------------------- #
# 在线：只读探测（无登录提交）
# --------------------------------------------------------------------------- #
@pytest.mark.live
def test_live_captcha_probe_is_read_only() -> None:
    """verifyCodeIsNeed 只读探测：返回布尔且不触发 4333。"""
    need = scholar.iam_captcha_required("cnki")
    assert isinstance(need, bool)


@pytest.mark.live
def test_live_sso_alive_probe() -> None:
    """sso_alive 只读探测：返回结构完整、布尔判定（不弹浏览器、不提交登录）。"""
    result = scholar.sso_alive("cnki")
    assert isinstance(result["logged_in"], bool)
    assert result["detail"]
    if result["logged_in"]:
        # 活会话必须已离开身份层（IdP 静默放行到数据库侧）
        assert "idp.westlake.edu.cn" not in result["final_url"]
        assert "iam.westlake.edu.cn" not in result["final_url"]
