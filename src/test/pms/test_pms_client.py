"""客户端杂项：根地址解析、单例工厂、支付封装、未实现动作。"""

from __future__ import annotations

import pytest

from pms_fakes import TEST_BASE, FakeResponse, envelope

import westlake_survival.pms as pms_module
from westlake_survival.pms import PMS_BASE, PMSClient, pms, reset_pms, resolve_base_url


def test_default_base_is_real_controller():
    assert PMS_BASE == "http://print.lib.westlake.edu.cn:9130"
    assert PMSClient(session=None).base_url == PMS_BASE


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv("WESTLAKE_PMS_BASE", "http://127.0.0.1:9999/")
    assert resolve_base_url() == "http://127.0.0.1:9999"
    assert PMSClient().base_url == "http://127.0.0.1:9999"


def test_explicit_base_url_wins(monkeypatch):
    monkeypatch.setenv("WESTLAKE_PMS_BASE", "http://ignored:1")
    client = PMSClient(base_url="http://explicit")
    assert client.base_url == "http://explicit"


def test_constructor_does_not_send_requests():
    """构造客户端必须是纯本地的——不读凭据、不发请求。"""
    client = PMSClient(base_url="http://x")
    assert client.is_logged_in is False
    assert client.user is None
    assert client.session_id is None


def test_singleton_factory(session):
    reset_pms()
    first = pms()
    second = pms()
    assert first is second
    # 带凭据调用会重建
    third = pms(username="u", password="p")
    assert third is not first
    assert pms() is third
    reset_pms()
    assert pms() is not third


# --------------------------------------------------------------------------
# 支付封装
# --------------------------------------------------------------------------


def test_get_bill_passthrough(client, session):
    session.add("/api/client/Pay/GetBill", FakeResponse(envelope({"dwFee": 100})))
    result = client.get_bill({"dwJobId": 501})
    call = session.calls[0]
    assert call["url"] == f"{TEST_BASE}/api/client/Pay/GetBill"
    assert call["json"] == {"dwJobId": 501}
    assert result["dwFee"] == 100


def test_recharge_params(client, session):
    session.add("/api/client/Pay/Recharge", FakeResponse(envelope()))
    client.recharge(sz_type="card", dw_fee=1000, state="ok", operator="op", memo="top up")
    params = session.calls[0]["params"]
    assert params == {
        "szType": "card",
        "dwFee": 1000,
        "state": "ok",
        "szOperator": "op",
        "szMemo": "top up",
    }


def test_recharge_minimal_params(client, session):
    session.add("/api/client/Pay/Recharge", FakeResponse(envelope()))
    client.recharge()
    assert session.calls[0]["params"] == {"szType": "", "dwFee": 0, "state": ""}


def test_pay_result_and_wait(client, session):
    session.add("/api/client/Pay/GetPayResult", FakeResponse(envelope({"paid": True})))
    session.add("/api/client/Pay/WaitPayResult", FakeResponse(envelope({"paid": True})))
    assert client.pay_result()["paid"] is True
    assert client.wait_pay_result()["paid"] is True


def test_pay_methods_document_the_warning():
    """支付方法的 docstring 必须带风险提示。"""
    assert "一卡通" in PMSClient.recharge.__doc__
    assert "谨慎" in PMSClient.recharge.__doc__ or "扣款" in PMSClient.recharge.__doc__


# --------------------------------------------------------------------------
# 未实现动作
# --------------------------------------------------------------------------


def test_unimplemented_raises_not_implemented(client):
    with pytest.raises(NotImplementedError) as excinfo:
        client.submit_print_job()
    assert "api_notes.md" in str(excinfo.value)


def test_change_password_sends_expected_body(session):
    client = PMSClient(username="u1", password="p1", session=session, base_url=TEST_BASE)
    session.add("/api/client/Auth/ChgPassword", FakeResponse(envelope()))
    client.change_password("old", "new")
    body = session.calls[0]["json"]
    assert body == {"szLogonName": "u1", "szOldPassword": "old", "szNewPassword": "new"}


def test_module_exports_expected_names():
    for name in ("PMSClient", "pms", "PrintJob", "ScanJob", "Station", "UsageRecord"):
        assert hasattr(pms_module, name)


# --------------------------------------------------------------------------
# sso 惰性导入的降级路径
# --------------------------------------------------------------------------


def test_default_credentials_lazy_import(monkeypatch):
    """模块级导入失败（_read_credentials 为 None）时应延迟导入并回填。"""
    from westlake_survival.pms import client as pms_client

    monkeypatch.setattr(pms_client, "_read_credentials", None)
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "20210000:pw")
    assert pms_client.default_credentials() == ("20210000", "pw")
    assert pms_client._read_credentials is not None  # 已回填缓存


def test_default_credentials_import_failure(monkeypatch):
    """连延迟导入也失败时抛 AuthError（而不是 ImportError）。"""
    import builtins

    from westlake_survival.exceptions import AuthError
    from westlake_survival.pms import client as pms_client

    monkeypatch.setattr(pms_client, "_read_credentials", None)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "westlake_survival.sso":
            raise ImportError("simulated missing sso")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(AuthError) as excinfo:
        pms_client.default_credentials()
    assert "read_credentials" in str(excinfo.value)
