"""可选 ``keyring`` 后端：优先级、异常回退、读写删。

用 ``monkeypatch.setitem(sys.modules, "keyring", ...)`` 注入假实现，全程离线、
不触碰真实系统钥匙串。所有用例在**未安装 keyring** 的本仓环境下同样可跑。
"""

from __future__ import annotations

import sys
import types

import pytest

from westlake_survival.sso import creds


class FakeKeyring(types.ModuleType):
    """最小化 keyring 替身：内存 dict + 可配置的异常注入。"""

    def __init__(
        self,
        *,
        raise_on_get: bool = False,
        raise_on_set: bool = False,
        raise_on_delete: bool = False,
    ) -> None:
        super().__init__("keyring")
        self.store: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.raise_on_get = raise_on_get
        self.raise_on_set = raise_on_set
        self.raise_on_delete = raise_on_delete

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        if self.raise_on_set:
            raise RuntimeError("keyring 后端写入失败")
        self.store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        if self.raise_on_get:
            raise RuntimeError("keyring 后端读取失败")
        return self.store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        if self.raise_on_delete:
            raise RuntimeError("keyring 后端删除失败")
        if (service, username) not in self.store:
            raise KeyError("no such entry")
        del self.store[(service, username)]


def install_fake_keyring(monkeypatch, **kwargs) -> FakeKeyring:
    fake = FakeKeyring(**kwargs)
    monkeypatch.setitem(sys.modules, "keyring", fake)
    # 用例的配置根都在临时目录（conftest 的 autouse 夹具），默认会被
    # ``keyring_isolated()`` 判为沙箱而整体跳过；这里显式放开，才走得到钥匙串分支。
    monkeypatch.setattr(creds, "keyring_isolated", lambda: False)
    return fake


def make_keyring_unavailable(monkeypatch) -> None:
    """让 ``import keyring`` 抛 ImportError（模拟未安装）。"""
    monkeypatch.setitem(sys.modules, "keyring", None)


def write_file_creds(tmp_path, content: str = "file_sid:file_pwd") -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "credentials.txt").write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
# keyring_available
# --------------------------------------------------------------------------- #
def test_keyring_available_true_with_fake_module(monkeypatch):
    install_fake_keyring(monkeypatch)
    assert creds.keyring_available() is True


def test_keyring_available_false_when_not_installed(monkeypatch):
    make_keyring_unavailable(monkeypatch)
    assert creds.keyring_available() is False


def test_keyring_available_false_on_import_exception(monkeypatch):
    """导入期抛非 ImportError 的异常也必须吞掉并返回 False。"""

    class BoomFinder:
        def find_module(self, name, path=None):  # pragma: no cover - 旧式协议
            return None

        def find_spec(self, name, path=None, target=None):
            if name == "keyring":
                raise RuntimeError("后端初始化时炸了")
            return None

    monkeypatch.delitem(sys.modules, "keyring", raising=False)
    monkeypatch.setattr(sys, "meta_path", [BoomFinder(), *sys.meta_path])
    assert creds.keyring_available() is False


# --------------------------------------------------------------------------- #
# 四级优先级
# --------------------------------------------------------------------------- #
def test_priority_memory_beats_keyring_and_file(monkeypatch, tmp_path):
    install_fake_keyring(monkeypatch).store[(creds.KEYRING_SERVICE, "k_sid")] = "k_pwd"
    creds.save_credentials_keyring("k_sid", "k_pwd")
    creds.cred_set("mem_sid", "mem_pwd")
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "env_sid:env_pwd")
    write_file_creds(tmp_path)
    assert creds.read_credentials() == ("mem_sid", "mem_pwd")


def test_priority_env_beats_keyring_and_file(monkeypatch, tmp_path):
    install_fake_keyring(monkeypatch)
    creds.save_credentials_keyring("k_sid", "k_pwd")
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "env_sid:env_pwd")
    write_file_creds(tmp_path)
    assert creds.read_credentials() == ("env_sid", "env_pwd")


def test_priority_keyring_beats_file(monkeypatch, tmp_path):
    install_fake_keyring(monkeypatch)
    assert creds.save_credentials_keyring("k_sid", "k_pwd") is True
    write_file_creds(tmp_path)
    assert creds.read_credentials() == ("k_sid", "k_pwd")


def test_file_used_when_keyring_empty(monkeypatch, tmp_path):
    install_fake_keyring(monkeypatch)  # 可用但无条目
    write_file_creds(tmp_path)
    assert creds.read_credentials() == ("file_sid", "file_pwd")


def test_file_used_when_keyring_not_installed(monkeypatch, tmp_path):
    """无 keyring 环境下，现状三级行为零变化。"""
    make_keyring_unavailable(monkeypatch)
    write_file_creds(tmp_path)
    assert creds.read_credentials() == ("file_sid", "file_pwd")


def test_nothing_available_still_raises(monkeypatch):
    from westlake_survival.exceptions import AuthError

    make_keyring_unavailable(monkeypatch)
    with pytest.raises(AuthError):
        creds.read_credentials()


# --------------------------------------------------------------------------- #
# read_credentials_keyring
# --------------------------------------------------------------------------- #
def test_read_keyring_none_when_pointer_absent(monkeypatch):
    install_fake_keyring(monkeypatch)
    assert creds.read_credentials_keyring() is None


def test_read_keyring_none_when_password_absent(monkeypatch):
    fake = install_fake_keyring(monkeypatch)
    fake.store[(creds.KEYRING_SERVICE, creds.KEYRING_SID_KEY)] = "k_sid"
    # 只有指针项、没有密码项：
    assert creds.read_credentials_keyring() is None


def test_read_keyring_roundtrip(monkeypatch):
    install_fake_keyring(monkeypatch)
    creds.save_credentials_keyring("2021001", "secret")
    assert creds.read_credentials_keyring() == ("2021001", "secret")


def test_read_keyring_exception_treated_unavailable_falls_back_to_file(monkeypatch, tmp_path):
    install_fake_keyring(monkeypatch, raise_on_get=True)
    write_file_creds(tmp_path)
    assert creds.read_credentials_keyring() is None
    assert creds.read_credentials() == ("file_sid", "file_pwd")


def test_read_keyring_none_when_unavailable(monkeypatch):
    make_keyring_unavailable(monkeypatch)
    assert creds.read_credentials_keyring() is None


# --------------------------------------------------------------------------- #
# save / delete
# --------------------------------------------------------------------------- #
def test_save_keyring_returns_false_when_unavailable(monkeypatch):
    make_keyring_unavailable(monkeypatch)
    assert creds.save_credentials_keyring("s", "p") is False


def test_save_keyring_returns_false_on_backend_error(monkeypatch):
    install_fake_keyring(monkeypatch, raise_on_set=True)
    assert creds.save_credentials_keyring("s", "p") is False


def test_save_keyring_stores_password_and_pointer(monkeypatch):
    fake = install_fake_keyring(monkeypatch)
    assert creds.save_credentials_keyring("2021001", "secret") is True
    assert fake.store[(creds.KEYRING_SERVICE, "2021001")] == "secret"
    assert fake.store[(creds.KEYRING_SERVICE, creds.KEYRING_SID_KEY)] == "2021001"


def test_delete_keyring_removes_entries(monkeypatch):
    fake = install_fake_keyring(monkeypatch)
    creds.save_credentials_keyring("2021001", "secret")
    assert creds.delete_credentials_keyring() is True
    assert fake.store == {}
    assert creds.read_credentials_keyring() is None


def test_delete_keyring_false_when_unavailable(monkeypatch):
    make_keyring_unavailable(monkeypatch)
    assert creds.delete_credentials_keyring() is False


def test_delete_keyring_tolerates_missing_entries(monkeypatch):
    fake = install_fake_keyring(monkeypatch)
    fake.store[(creds.KEYRING_SERVICE, creds.KEYRING_SID_KEY)] = "ghost_sid"
    # 指针指向的密码项并不存在：删除指针项后整体仍应成功。
    assert creds.delete_credentials_keyring() is True
    assert fake.store == {}


def test_delete_keyring_returns_false_on_backend_error(monkeypatch):
    fake = install_fake_keyring(monkeypatch, raise_on_delete=True)
    fake.store[(creds.KEYRING_SERVICE, creds.KEYRING_SID_KEY)] = "2021001"
    assert creds.delete_credentials_keyring() is False


def test_write_credentials_unaffected_by_keyring(monkeypatch, tmp_path):
    """keyring 可用时 ``write_credentials`` 仍只写文件（CLI 集成单元另调新函数）。"""
    fake = install_fake_keyring(monkeypatch)
    path = creds.write_credentials("2021001", "secret")
    assert path.read_text(encoding="utf-8") == "2021001:secret"
    assert fake.store == {}
    assert fake.calls == []
