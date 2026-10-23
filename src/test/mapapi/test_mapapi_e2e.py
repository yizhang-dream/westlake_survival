"""电子地图会话（mapapi）端到端测试：真实接口、真实凭据来源、真实错误码。

默认被 ``-m 'not live'`` 排除；真实验证：
``pytest src/test/mapapi/test_mapapi_e2e.py -q -m live``。

账号相关用例**只用明显虚构的账号**（``e2e-bogus-*``），不碰用户真实账号，
避免锁号；真实账号登录由 ``westlake map login`` 在用户授权下手动触发。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.campusmap import cli_group
from westlake_survival.exceptions import AuthError
from westlake_survival.mapapi import map_cred_status, ping


@pytest.mark.live
def test_live_ping_accepts_generated_headers() -> None:
    """三个必需头（nonce/timestamp/client-id）被服务端接受，返回系统名。"""
    assert ping() == "西湖大学电子地图系统"


@pytest.mark.live
def test_live_bogus_account_is_rejected_as_auth_error() -> None:
    """虚构账号登录：服务端返回 20002（用户不存在），被翻译成 AuthError。

    这条用例证明「请求格式正确、凭据被真正校验」——若头不对会得到 10041；
    真实存在的账号密码错则得到 20001。两者语义不同，错误信息要能区分。
    """
    from westlake_survival.mapapi import login

    with pytest.raises(AuthError) as excinfo:
        login("e2e-bogus-user", "e2e-bogus-password")
    message = str(excinfo.value)
    assert "20002" in message
    assert "不存在" in message


@pytest.mark.live
def test_live_cred_status_reports_sources_without_secrets() -> None:
    """状态查询只报有无，且键面齐全。"""
    status = map_cred_status()

    assert "sources" in status
    assert set(status["sources"]) >= {"内存", "keyring"}
    assert isinstance(status["has_credentials"], bool)
    assert isinstance(status["token_valid"], bool)
    # 泄露检查：任何字段都不应包含冒号式密码形态的长串
    rendered = repr(status)
    assert "e2e-bogus" not in rendered


def test_cli_map_status_runs() -> None:
    """`westlake map status` 在无凭据时也能正常输出并给出配置提示。"""
    result = CliRunner().invoke(cli_group, ["status"])

    assert result.exit_code == 0, result.output
    assert "电子地图" in result.output
    if "可用凭据：无" in result.output:
        assert "westlake map login" in result.output
