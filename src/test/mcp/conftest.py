"""MCP server 测试的公共夹具。

全部用例**离线**：协议层用 ``handle_line`` / ``serve`` 直接喂 JSON 行；
工具层通过 ``monkeypatch`` 打桩各业务模块的公开函数，不发起任何网络请求。
"""

from __future__ import annotations

import pytest

from westlake_survival.canvas import reset_canvas


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """清掉凭据 / token 环境变量，并把配置根重定位到临时目录。"""
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WESTLAKE_CANVAS_TOKEN", raising=False)
    reset_canvas()
    yield
    reset_canvas()
