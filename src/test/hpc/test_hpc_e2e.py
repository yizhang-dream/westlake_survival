"""hpc 模块端到端测试（live）：Westlake AI 网关 + /hpc 页。"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.live


def _mod():
    return importlib.import_module("westlake_survival.hpc")


def test_ai_service_info() -> None:
    """Westlake AI 网关信息：地址 / 领令牌 / 模型清单齐。"""
    mod = _mod()
    info = mod.ai_service()
    assert info["gateway"] == "https://hpc-api.westlake.edu.cn/v1"
    assert info["key_url"].startswith("https://hpc.westlake.edu.cn/")
    assert {"GLM-5.3-Flash", "DeepSeek-V4.1-Flash", "Qwen 3.8"} <= set(info["models"])
    assert info["tool_panels"]


def test_ai_gateway_probe_alive() -> None:
    """网关探测：无令牌 401 = New API 网关在役。"""
    mod = _mod()
    probe = mod.ai_gateway_probe()
    assert probe["alive"], probe
    assert probe["status"] in (401, 403)


def test_webui_hpc_page_ai_card() -> None:
    """/hpc 页渲染 Westlake AI 服务卡（复用常驻 webui，未运行则跳过）。"""
    import urllib.request

    try:
        html = urllib.request.urlopen("http://127.0.0.1:2018/hpc", timeout=60).read().decode("utf-8")
    except Exception:
        pytest.skip("本地 webui 未运行")
    for marker in ("Westlake AI", "hpc-api.westlake.edu.cn", "私有令牌申请", "GLM-5.3-Flash"):
        assert marker in html, marker
