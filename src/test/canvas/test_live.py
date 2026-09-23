"""live 探测测试：验证 canvas.westlake.edu.cn 的 REST API 是否开放。

默认被 ``addopts = -m 'not live'`` 排除，需显式 ``pytest -m live`` 运行。
不带 token，仅探测匿名请求的状态码——用来记录学校侧的现状（API 是否
启用、是否强制认证），不做任何凭证尝试。
"""

from __future__ import annotations

import os

import requests
import pytest

from westlake_survival._net import DEFAULT_TIMEOUT, USER_AGENT

CANVAS_ORIGIN = "https://canvas.westlake.edu.cn"


@pytest.mark.live
def test_users_self_requires_auth_or_is_hidden():
    """GET /api/v1/users/self 无 token：应为 401（未认证）或 404（隐藏）。"""
    response = requests.get(
        f"{CANVAS_ORIGIN}/api/v1/users/self",
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
    )
    # 两种都接受：401 = API 开启且校验认证；404 = 该端点对匿名不可见。
    assert response.status_code in (401, 404), (
        f"unexpected status {response.status_code}: {response.text[:200]}"
    )
    assert response.headers.get("x-canvas-meta") is not None  # 确认是 Canvas 服务


@pytest.mark.live
def test_courses_endpoint_requires_auth():
    """GET /api/v1/courses 无 token：应为 401，证明 API 已开放。"""
    response = requests.get(
        f"{CANVAS_ORIGIN}/api/v1/courses",
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
    )
    assert response.status_code == 401, (
        f"unexpected status {response.status_code}: {response.text[:200]}"
    )


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("WESTLAKE_CANVAS_TOKEN"),
    reason="需要真实 WESTLAKE_CANVAS_TOKEN 才跑",
)
def test_exams_end_to_end_with_real_token():
    """带真实 token 时，exams() 应能跑通并返回列表（可能为空）。"""
    from westlake_survival.canvas import CanvasClient

    client = CanvasClient()
    items = client.exams()
    assert isinstance(items, list)
    for item in items:
        assert item.kind in ("quiz", "calendar-event")

