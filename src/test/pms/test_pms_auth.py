"""认证流程测试：PublicKey → GetAuthToken → Login / Check / Logout。

公钥用**真实结构**（X.509 SubjectPublicKeyInfo）；测试时现生成一把 512-bit
RSA 密钥，既能验证 :func:`~westlake_survival.pms.client.encrypt_password` 的
PKCS#1 v1.5 编码，也能用私钥把密文解回来核对明文（往返验证）。
"""

from __future__ import annotations

import base64
import random
from math import gcd

import pytest

from pms_fakes import TEST_BASE, FakeResponse, envelope

from westlake_survival.exceptions import (
    ActionError,
    AuthError,
    InvalidCredentials,
    OffCampusError,
    ParseError,
    SessionExpired,
)
from westlake_survival.pms import PMSClient, encrypt_password, rsa_public_numbers

# --------------------------------------------------------------------------
# 临时 RSA 密钥（仅测试用）
# --------------------------------------------------------------------------


def _is_probable_prime(n: int, rounds: int = 24) -> bool:
    if n < 2:
        return False
    for small in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % small == 0:
            return n == small
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    rng = random.Random(1234)
    for _ in range(rounds):
        a = rng.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def _der_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _der_int(value: int) -> bytes:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + _der_len(len(raw)) + raw


def _der_seq(*parts: bytes) -> bytes:
    body = b"".join(parts)
    return b"\x30" + _der_len(len(body)) + body


@pytest.fixture(scope="module")
def rsa_key() -> dict:
    """返回一把临时的 512-bit RSA 密钥及其 SPKI base64 编码。"""
    rng = random.Random(20260922)
    while True:
        p = _gen_prime(256, rng)
        q = _gen_prime(256, rng)
        if p == q:
            continue
        n = p * q
        if n.bit_length() == 512:
            break
    e = 65537
    lam = (p - 1) * (q - 1) // gcd(p - 1, q - 1)
    d = pow(e, -1, lam)
    alg = _der_seq(b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x01\x01", b"\x05\x00")
    rsa_seq = _der_seq(_der_int(n), _der_int(e))
    bit_string = b"\x03" + _der_len(len(rsa_seq) + 1) + b"\x00" + rsa_seq
    spki = _der_seq(alg, bit_string)
    return {
        "b64": base64.b64encode(spki).decode("ascii"),
        "n": n,
        "e": e,
        "d": d,
        "size": (n.bit_length() + 7) // 8,
    }


def _decrypt(rsa_key: dict, ciphertext_b64: str) -> bytes:
    """用私钥解回明文（验证 PKCS#1 v1.5 编码正确）。"""
    size = rsa_key["size"]
    cipher = int.from_bytes(base64.b64decode(ciphertext_b64), "big")
    block = pow(cipher, rsa_key["d"], rsa_key["n"]).to_bytes(size, "big")
    assert block[:2] == b"\x00\x02", "PKCS#1 v1.5 块头错误"
    index = block.index(b"\x00", 2)
    return block[index + 1 :]


# --------------------------------------------------------------------------
# 纯函数：公钥解析与密码加密
# --------------------------------------------------------------------------

#: 线上实测拿到的公钥（1024-bit）。
LIVE_PUBLIC_KEY = (
    "MIGdMA0GCSqGSIb3DQEBAQUAA4GLADCBhwKBgQCpKg2D+cg0m+RY2mMvqHgltqXEsrnsXc+t4jhGP28j"
    "JTf7S7PBk4vLgIdfhGW+d2xrRh3mtHvz3xseFQUMHO+seFWw77ym4qFwSx638jbAWM656mxmZr4/q1tY"
    "SNKLg37QSWYI4TRMbtnUvCWGtlwnq7GgY3ykmDUykTJqDveOYwIBAw=="
)


def test_rsa_public_numbers(rsa_key):
    n, e = rsa_public_numbers(rsa_key["b64"])
    assert n == rsa_key["n"]
    assert e == 65537


def test_live_public_key_is_parsable():
    """线上公钥能被纯标准库解析（128 字节模长，e=3 —— 实测值）。"""
    n, e = rsa_public_numbers(LIVE_PUBLIC_KEY)
    assert (n.bit_length() + 7) // 8 == 128
    assert e == 3  # 该控制器用的是 e=3，不是常见的 65537


def test_rsa_public_numbers_rejects_garbage():
    with pytest.raises(ValueError):
        rsa_public_numbers("not-a-der-structure")


def test_encrypt_password_roundtrip(rsa_key):
    cipher = encrypt_password("S3cret!", rsa_key["b64"], "nonce-hex")
    assert _decrypt(rsa_key, cipher) == b"S3cret!;nonce-hex"
    assert len(base64.b64decode(cipher)) == rsa_key["size"]


def test_encrypt_password_is_randomized(rsa_key):
    first = encrypt_password("pw", rsa_key["b64"], "n")
    second = encrypt_password("pw", rsa_key["b64"], "n")
    assert first != second  # PS 随机，密文不同
    assert _decrypt(rsa_key, first) == _decrypt(rsa_key, second) == b"pw;n"


def test_encrypt_password_too_long(rsa_key):
    with pytest.raises(ValueError):
        encrypt_password("x" * 200, rsa_key["b64"], "n")


# --------------------------------------------------------------------------
# 认证端点
# --------------------------------------------------------------------------


def test_public_key(client, session):
    session.add(
        "/api/client/Auth/PublicKey",
        FakeResponse(envelope({"publicKey": LIVE_PUBLIC_KEY, "nonceStr": "abc123"})),
    )
    public_key, nonce = client.public_key()
    assert public_key == LIVE_PUBLIC_KEY
    assert nonce == "abc123"
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == f"{TEST_BASE}/api/client/Auth/PublicKey"


def test_public_key_missing_field(client, session):
    session.add("/api/client/Auth/PublicKey", FakeResponse(envelope({})))
    with pytest.raises(ParseError):
        client.public_key()


def test_auth_token_reads_top_level_field(client, session):
    session.add(
        "/api/client/Auth/GetAuthToken",
        FakeResponse(
            {
                "szAuthType": "password",
                "szInfo": None,
                "szToken": "51c6b42c396a4508a26ac4d8b20e1e46",
                "szStaSessionId": None,
                "code": 0,
                "message": "",
                "result": None,
            }
        ),
    )
    assert client.auth_token() == "51c6b42c396a4508a26ac4d8b20e1e46"
    assert session.calls[0]["method"] == "POST"


def test_auth_token_failure(client, session):
    session.add(
        "/api/client/Auth/GetAuthToken",
        FakeResponse({"code": 1, "message": "参数错误", "result": None}),
    )
    with pytest.raises(AuthError):
        client.auth_token()


def test_login_full_flow(session, rsa_key):
    session.add(
        "/api/client/Auth/PublicKey",
        FakeResponse(envelope({"publicKey": rsa_key["b64"], "nonceStr": "n0nce"})),
    )
    session.add(
        "/api/client/Auth/GetAuthToken",
        FakeResponse(
            {
                "szAuthType": "password",
                "szToken": "tok-123",
                "code": 0,
                "message": "",
                "result": None,
            }
        ),
    )
    session.add(
        "/api/client/Auth/Login",
        FakeResponse(
            envelope(
                {
                    "szLogonName": "20210000",
                    "szTrueName": "张三",
                    "dwSex": 1,
                    "szEmail": "z@westlake.edu.cn",
                }
            )
        ),
    )

    client = PMSClient(
        username="20210000", password="pw!", session=session, base_url=TEST_BASE
    )
    user = client.login()

    assert user["szTrueName"] == "张三"
    assert client.user == user
    assert client.is_logged_in

    # 调用顺序：PublicKey → GetAuthToken → Login
    assert session.paths() == [
        "/api/client/Auth/PublicKey",
        "/api/client/Auth/GetAuthToken",
        "/api/client/Auth/Login",
    ]

    body = session.calls_for("/api/client/Auth/Login")[0]["json"]
    assert body["szLogonName"] == "20210000"
    assert body["szToken"] == "tok-123"
    # 密码不是明文，且能解回 password;nonce
    assert body["szPassword"] != "pw!"
    assert _decrypt(rsa_key, body["szPassword"]) == b"pw!;n0nce"


def test_login_bad_credentials(session, rsa_key):
    session.add(
        "/api/client/Auth/PublicKey",
        FakeResponse(envelope({"publicKey": rsa_key["b64"], "nonceStr": "n"})),
    )
    session.add(
        "/api/client/Auth/GetAuthToken",
        FakeResponse({"szToken": "tok", "code": 0, "message": "", "result": None}),
    )
    session.add(
        "/api/client/Auth/Login",
        FakeResponse(envelope(None, code=1, message="账号或密码错误")),
    )
    client = PMSClient(username="20210000", password="wrong", session=session, base_url=TEST_BASE)
    with pytest.raises(InvalidCredentials) as excinfo:
        client.login()
    assert "账号或密码错误" in str(excinfo.value)
    assert client.user is None


def test_login_without_credentials_raises_auth_error(session, monkeypatch, tmp_path):
    monkeypatch.delenv("WESTLAKE_CREDENTIALS", raising=False)
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))  # 空目录，无 credentials.txt
    client = PMSClient(session=session, base_url=TEST_BASE)
    with pytest.raises(AuthError):
        client.resolve_credentials()


def test_explicit_credentials_win(session):
    client = PMSClient(username="u1", password="p1", session=session, base_url=TEST_BASE)
    assert client.resolve_credentials() == ("u1", "p1")


def test_partial_credentials_rejected(session, monkeypatch, tmp_path):
    monkeypatch.delenv("WESTLAKE_CREDENTIALS", raising=False)
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path))
    client = PMSClient(username="u1", session=session, base_url=TEST_BASE)
    with pytest.raises(AuthError):
        client.resolve_credentials()


def test_check_logged_in(client, session):
    session.add(
        "/api/client/Auth/Check",
        FakeResponse(
            {
                "code": 0,
                "message": "",
                "result": {"szLogonName": "20210000", "szTrueName": "张三"},
                "SessionId": "sess-1",
            }
        ),
    )
    user = client.check()
    assert user == {"szLogonName": "20210000", "szTrueName": "张三"}
    assert client.session_id == "sess-1"
    assert session.calls[0]["method"] == "POST"


def test_check_not_logged_in_returns_none(client, session):
    session.add(
        "/api/client/Auth/Check",
        FakeResponse(envelope(None, code=4, message="无效会话，未登录")),
    )
    assert client.check() is None
    assert client.user is None


def test_ensure_logged_in_reuses_existing_session(client, session):
    """Check 通过时不应再触发 Login。"""
    session.add("/api/client/Auth/Check", FakeResponse(envelope({"szTrueName": "李四"})))
    user = client.ensure_logged_in()
    assert user["szTrueName"] == "李四"
    assert session.calls_for("/api/client/Auth/Login") == []


def test_logout(client, session):
    session.add("/api/client/Auth/Logout", FakeResponse(envelope("http://x/login")))
    client.logout()
    assert client.user is None
    assert client.session_id is None


def test_logout_failure(client, session):
    session.add("/api/client/Auth/Logout", FakeResponse(envelope(None, code=9, message="退出失败")))
    with pytest.raises(ActionError):
        client.logout()


def test_user_info_returns_raw_dict(client, session):
    session.add(
        "/api/client/Auth/GetUserInfo",
        FakeResponse(envelope({"szLogonName": "20210000", "szTrueName": "王五", "dwSex": 0})),
    )
    assert client.user_info()["szTrueName"] == "王五"


def test_session_expired_mapping(client, session):
    """code == 4 → SessionExpired（而不是普通 ActionError）。"""
    session.add(
        "/api/client/PrintJob/Get",
        FakeResponse(envelope(None, code=4, message="无效会话，未登录")),
    )
    with pytest.raises(SessionExpired) as excinfo:
        client.list_print_jobs()
    assert "无效会话" in str(excinfo.value)


def test_non_json_response_raises_parse_error(client, session):
    session.add("/api/client/Station/GetList", FakeResponse(None, text="<html>oops</html>"))
    with pytest.raises(ParseError):
        client.list_stations()


def test_envelope_without_code_raises_parse_error(client, session):
    session.add("/api/client/Station/GetList", FakeResponse({"foo": "bar"}))
    with pytest.raises(ParseError):
        client.list_stations()


def test_connection_error_maps_to_offcampus(client, session):
    import requests

    def boom(*args, **kwargs):
        raise requests.ConnectionError("boom")

    session.request = boom  # type: ignore[method-assign]
    with pytest.raises(OffCampusError) as excinfo:
        client.list_stations()
    assert "VPN" in str(excinfo.value)


def test_http_404_maps_to_not_found(client, session):
    from westlake_survival.exceptions import NotFound

    session.add(
        "/api/client/Station/GetList",
        FakeResponse({"Message": "No HTTP resource"}, status_code=404),
    )
    with pytest.raises(NotFound):
        client.list_stations()
