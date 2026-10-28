"""``westlake sso creds`` 的 keyring 集成测试（monkeypatch 假 keyring 函数）。

``cli.main`` 按候选名探测 ``sso.creds`` 的 keyring 接口（首选
``save_credentials_keyring`` / ``read_credentials_keyring``）；这里 monkeypatch
这些函数来驱动 CLI，并额外验证「函数不存在时降级原有行为」。
"""

from __future__ import annotations

from westlake_survival.sso import creds as creds_mod


def _install_fake_keyring(
    monkeypatch, *, available=True, stored=None, write_error=None, write_result=True
):
    """给 creds 模块挂上一套假 keyring 接口，返回记录写入的容器。"""
    box: dict[str, str] = dict(stored or {})

    def write(sid, password):
        if write_error is not None:
            raise write_error
        box["sid"], box["password"] = sid, password
        return write_result

    def read():
        if box.get("sid") and box.get("password"):
            return box["sid"], box["password"]
        return None

    monkeypatch.setattr(creds_mod, "keyring_available", lambda: available, raising=False)
    monkeypatch.setattr(creds_mod, "save_credentials_keyring", write, raising=False)
    monkeypatch.setattr(creds_mod, "read_credentials_keyring", read, raising=False)
    # 夹具把配置根放在临时目录，默认按沙箱处理（不碰钥匙串）；这些用例要验证
    # 钥匙串分支本身，故显式放开——写入的是上面的假实现，不接触真实后端。
    monkeypatch.setattr(creds_mod, "keyring_isolated", lambda: False, raising=False)
    return box


def test_creds_set_keyring_writes_keyring(runner, cli_group, isolated_home, monkeypatch) -> None:
    """缺省且 keyring 可用：写入钥匙串，不落明文文件。"""
    box = _install_fake_keyring(monkeypatch)
    result = runner.invoke(
        cli_group, ["sso", "creds", "set", "--sid", "20210000", "--password", "pw"]
    )
    assert result.exit_code == 0, result.output
    assert box == {"sid": "20210000", "password": "pw"}
    assert "keyring" in result.output
    assert not (isolated_home / "credentials.txt").exists()


def test_creds_set_no_keyring_forces_file(runner, cli_group, isolated_home, monkeypatch) -> None:
    """--no-keyring 走原文件路径。"""
    box = _install_fake_keyring(monkeypatch)
    result = runner.invoke(
        cli_group,
        ["sso", "creds", "set", "--sid", "20210000", "--password", "pw", "--no-keyring"],
    )
    assert result.exit_code == 0, result.output
    assert box == {}
    assert (isolated_home / "credentials.txt").read_text(encoding="utf-8") == "20210000:pw"


def test_creds_set_keyring_unavailable_falls_back_to_file(
    runner, cli_group, isolated_home, monkeypatch
) -> None:
    """keyring 不可用：--keyring 也回退到文件并给警告。"""
    _install_fake_keyring(monkeypatch, available=False)
    result = runner.invoke(
        cli_group,
        ["sso", "creds", "set", "--sid", "20210000", "--password", "pw", "--keyring"],
    )
    assert result.exit_code == 0, result.output
    assert "keyring 不可用" in result.stderr
    assert (isolated_home / "credentials.txt").exists()


def test_creds_set_keyring_write_error_falls_back(
    runner, cli_group, isolated_home, monkeypatch
) -> None:
    """写钥匙串抛异常：回退文件并给警告。"""
    _install_fake_keyring(monkeypatch, write_error=RuntimeError("no backend"))
    result = runner.invoke(
        cli_group, ["sso", "creds", "set", "--sid", "20210000", "--password", "pw"]
    )
    assert result.exit_code == 0, result.output
    assert "写入 keyring 失败" in result.stderr
    assert (isolated_home / "credentials.txt").exists()


def test_creds_set_keyring_write_returns_false_falls_back(
    runner, cli_group, isolated_home, monkeypatch
) -> None:
    """写钥匙串返回 False（后端不可用契约）：回退文件。"""
    _install_fake_keyring(monkeypatch, write_result=False)
    result = runner.invoke(
        cli_group, ["sso", "creds", "set", "--sid", "20210000", "--password", "pw"]
    )
    assert result.exit_code == 0, result.output
    assert "keyring 后端不可用" in result.stderr
    assert (isolated_home / "credentials.txt").exists()


def test_creds_set_without_keyring_functions_still_works(
    runner, cli_group, isolated_home, monkeypatch
) -> None:
    """creds 未提供任何 keyring 函数时，set 走原文件路径、不报错。"""
    for name in (
        "keyring_available",
        "save_credentials_keyring",
        "read_credentials_keyring",
        "write_keyring_credentials",
        "keyring_write",
        "keyring_read",
    ):
        monkeypatch.delattr(creds_mod, name, raising=False)
    result = runner.invoke(
        cli_group, ["sso", "creds", "set", "--sid", "20210000", "--password", "pw"]
    )
    assert result.exit_code == 0, result.output
    assert (isolated_home / "credentials.txt").exists()


def test_creds_status_reports_four_sources(runner, cli_group, isolated_home, monkeypatch) -> None:
    """有 keyring 记录时：来源为 keyring，且四来源清单都出现。"""
    _install_fake_keyring(monkeypatch, stored={"sid": "20210000", "password": "pw"})
    result = runner.invoke(cli_group, ["sso", "creds", "status"])
    assert result.exit_code == 0, result.output
    assert "keyring" in result.output
    assert "内存" in result.output
    assert "环境变量" in result.output
    assert "配置文件" in result.output
    # 绝不回显密码。
    assert "pw" not in result.output


def test_creds_status_without_keyring_marks_unavailable(
    runner, cli_group, isolated_home, monkeypatch
) -> None:
    """无 keyring 接口时，状态里 keyring 标为不可用，仍列出四来源。"""
    for name in ("keyring_available", "read_credentials_keyring", "keyring_read"):
        monkeypatch.delattr(creds_mod, name, raising=False)
    result = runner.invoke(cli_group, ["sso", "creds", "status"])
    assert result.exit_code == 0, result.output
    assert "keyring：不可用" in result.output
    assert "凭据来源：无" in result.output
