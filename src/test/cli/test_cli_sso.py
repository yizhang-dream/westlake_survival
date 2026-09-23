"""``westlake sso`` 命令测试（无凭据路径、写入、登录、错误退出码）。"""

from __future__ import annotations

import pytest

from westlake_survival.exceptions import InvalidCredentials, OffCampusError
from westlake_survival.sso import read_credentials


def test_creds_status_without_credentials(runner, cli_group, isolated_home) -> None:
    """无凭据时应报「凭据来源：无」并列出配置路径。"""
    result = runner.invoke(cli_group, ["sso", "creds", "status"])
    assert result.exit_code == 0
    assert "凭据来源：无" in result.output
    assert "credentials.txt" in result.output


def test_creds_status_with_env(runner, cli_group, isolated_home, monkeypatch) -> None:
    monkeypatch.setenv("WESTLAKE_CREDENTIALS", "20210000:secret")
    result = runner.invoke(cli_group, ["sso", "creds", "status"])
    assert result.exit_code == 0
    assert "环境变量" in result.output
    # 绝不回显密码
    assert "secret" not in result.output


def test_creds_status_with_file(runner, cli_group, isolated_home) -> None:
    isolated_home.mkdir(parents=True, exist_ok=True)
    (isolated_home / "credentials.txt").write_text("20210000:pw", encoding="utf-8")
    result = runner.invoke(cli_group, ["sso", "creds", "status"])
    assert result.exit_code == 0
    assert "配置文件" in result.output


def test_creds_set_prompts_and_writes(runner, cli_group, isolated_home) -> None:
    """不带参数时交互输入，写入后可被 read_credentials 读到。"""
    result = runner.invoke(
        cli_group, ["sso", "creds", "set"], input="20210000\nmypassword\nmypassword\n"
    )
    assert result.exit_code == 0, result.output
    assert read_credentials() == ("20210000", "mypassword")
    assert (isolated_home / "credentials.txt").exists()


def test_login_success(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sso as sso_pkg

    class FakeSISAuth:
        def ensure(self) -> None:
            return None

    monkeypatch.setattr(sso_pkg, "SISAuth", FakeSISAuth)
    result = runner.invoke(cli_group, ["sso", "login"])
    assert result.exit_code == 0
    assert "登录成功" in result.output


def test_login_invalid_credentials_exit_1(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sso as sso_pkg

    class FakeSISAuth:
        def ensure(self) -> None:
            raise InvalidCredentials("用户名或密码错误")

    monkeypatch.setattr(sso_pkg, "SISAuth", FakeSISAuth)
    result = runner.invoke(cli_group, ["sso", "login"])
    assert result.exit_code == 1
    assert "错误" in result.stderr
    assert "用户名或密码错误" in result.stderr


def test_login_offcampus_hints_vpn(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.sso as sso_pkg

    class FakeSISAuth:
        def ensure(self) -> None:
            raise OffCampusError("仅校园网可达")

    monkeypatch.setattr(sso_pkg, "SISAuth", FakeSISAuth)
    result = runner.invoke(cli_group, ["sso", "login"])
    assert result.exit_code == 1
    assert "vpn.westlake.edu.cn" in result.stderr
