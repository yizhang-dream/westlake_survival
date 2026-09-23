"""在线探测测试（``@pytest.mark.live``，默认被 ``-m 'not live'`` 排除）。

只做**匿名 GET/POST 只读探测**，不登录、不发凭据：

- ``GET /api.html`` 必须 200，且页面里引用了真正的文档源
  ``/api/system/Help/Get``（api.html 只是 JS 壳）；
- 从 ``Help/Get`` 返回的 HTML 中至少能解析出 5 个控制器名；
- 匿名 ``GET /api/client/Station/GetList`` 能被本库正常解析。
"""

from __future__ import annotations

import re

import pytest

from westlake_survival._net import http_session
from westlake_survival.pms import PMS_BASE, PMSClient

pytestmark = pytest.mark.live

#: 文档 HTML 里控制器名的出现形式：<label>控制器:</label>server.controller.client.XxxController
_CONTROLLER_RE = re.compile(r"控制器:</label>\s*([\w.]+Controller)")
#: api.html 里引用的文档源。
_HELP_ENDPOINT_RE = re.compile(r'url:\s*"(/api/[^"]*Help[^"]*)"')


@pytest.fixture(scope="module")
def http():
    session = http_session()
    session.headers["Accept"] = "text/html,application/json"
    try:
        session.get(f"{PMS_BASE}/api.html", timeout=20).raise_for_status()
    except Exception as exc:  # pragma: no cover - 需要校内网络
        pytest.skip(f"无法访问文印控制器 {PMS_BASE}（需校园网/VPN）：{exc}")
    return session


def test_api_html_is_reachable_and_points_to_help(http):
    response = http.get(f"{PMS_BASE}/api.html", timeout=20)
    assert response.status_code == 200
    # api.html 是 JS 壳，真正的文档由 /api/system/Help/Get 提供
    match = _HELP_ENDPOINT_RE.search(response.text)
    assert match, "api.html 里没找到 Help 端点引用"
    assert match.group(1).startswith("/api/")


def test_help_document_lists_controllers(http):
    response = http.get(f"{PMS_BASE}/api/system/Help/Get", timeout=60)
    assert response.status_code == 200
    controllers = set(_CONTROLLER_RE.findall(response.text))
    assert len(controllers) >= 5, f"只解析出 {len(controllers)} 个控制器：{sorted(controllers)}"
    # 客户端打印相关控制器必须在列
    assert any(name.endswith("PrintJobController") for name in controllers)
    assert any(name.endswith("AuthController") for name in controllers)
    assert any(name.endswith("ScanController") for name in controllers)


def test_live_station_list_parses(http):
    """匿名 GET 网点列表并交给模型解析（验证真实响应与模型口径一致）。"""
    client = PMSClient(session=http, base_url=PMS_BASE)
    stations = client.list_stations()
    assert stations, "网点列表为空"
    assert all(station.dev_sn for station in stations)
    assert all(station.name for station in stations)
    # 实测每台设备都至少有纸盒与本机 IP
    assert any(station.papers for station in stations)
