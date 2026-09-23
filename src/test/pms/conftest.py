"""pms 测试的公共 fixture。

响应体严格按 ``api_notes.md`` 记录的真实信封
（``{"code":0,"message":"","result":...}``）与字段构造，**不发真实请求**。
假 HTTP 层见同目录 :mod:`pms_fakes`。
"""

from __future__ import annotations

import pytest

from pms_fakes import TEST_BASE, FakeSession

from westlake_survival.pms import PMSClient


@pytest.fixture
def session() -> FakeSession:
    """空的假 Session（测试里自行 ``session.add(path, response)``）。"""
    return FakeSession()


@pytest.fixture
def client(session: FakeSession) -> PMSClient:
    """无凭据、指向测试地址的客户端（构造时不会发请求）。"""
    return PMSClient(session=session, base_url=TEST_BASE)
