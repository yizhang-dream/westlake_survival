"""凭据三级优先级与解析边界。"""

from __future__ import annotations

import pytest

from westlake_survival.exceptions import AuthError
from westlake_survival.sso import creds


def test_memory_has_highest_priority(monkeypatch, tmp_path):
    creds.cred_set("mem_sid", "mem_pwd")
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "env_sid:env_pwd")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "credentials.txt").write_text("file_sid:file_pwd", encoding="utf-8")
    assert creds.read_credentials() == ("mem_sid", "mem_pwd")


def test_env_used_when_no_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "env_sid:env_pwd")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "credentials.txt").write_text("file_sid:file_pwd", encoding="utf-8")
    assert creds.read_credentials() == ("env_sid", "env_pwd")


def test_file_used_when_no_memory_or_env(tmp_path):
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "credentials.txt").write_text("file_sid:file_pwd", encoding="utf-8")
    assert creds.read_credentials() == ("file_sid", "file_pwd")


def test_cred_clear_removes_memory(monkeypatch):
    creds.cred_set("s", "p")
    creds.cred_clear()
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "env_sid:env_pwd")
    assert creds.read_credentials() == ("env_sid", "env_pwd")


def test_none_available_raises_with_guidance():
    with pytest.raises(AuthError) as excinfo:
        creds.read_credentials()
    message = str(excinfo.value)
    assert "WESTLAKE_CREDENTIALS" in message
    assert "cred_set" in message


def test_ascii_colon_split_on_first_colon(monkeypatch):
    # 密码里含 ASCII 冒号：只按第一个冒号切分，密码保留其余冒号。
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "sid:pa:ss:word")
    assert creds.read_credentials() == ("sid", "pa:ss:word")


def test_chinese_fullwidth_colon_fallback(monkeypatch):
    # 用户误输入全角冒号：无 ASCII 冒号时用全角冒号兜底。
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "2021001：secret")
    assert creds.read_credentials() == ("2021001", "secret")


def test_ascii_colon_wins_over_fullwidth(monkeypatch):
    # 同时含 ASCII 与全角冒号：以第一个 ASCII 冒号为准。
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "sid:pa：ss")
    assert creds.read_credentials() == ("sid", "pa：ss")


def test_missing_separator_raises(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "no-separator-here")
    with pytest.raises(AuthError):
        creds.read_credentials()


def test_empty_password_raises(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "sid:")
    with pytest.raises(AuthError):
        creds.read_credentials()


def test_empty_value_raises(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "   ")
    with pytest.raises(AuthError):
        creds.read_credentials()


def test_whitespace_is_stripped(monkeypatch):
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "  sid  :  pwd  ")
    assert creds.read_credentials() == ("sid", "pwd")


def test_write_credentials_roundtrip(tmp_path):
    path = creds.write_credentials("2021001", "secret")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "2021001:secret"
    assert creds.read_credentials() == ("2021001", "secret")


def test_write_credentials_is_under_config_root(tmp_path):
    path = creds.write_credentials("a", "b")
    assert path == creds.cred_path()
    assert path.parent == tmp_path / "home"