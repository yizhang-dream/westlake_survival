"""真实网络探测（需校园网；默认被 pyproject 的 -m 'not live' 排除）。

这些测试把 2026-09-22 的实测结论固化为断言：公开检索端点不可用、门户
JSON API 需登录。端点恢复后第一项会自动转为"断言返回非空"。
"""

from __future__ import annotations

import pytest
import requests

from westlake_survival.exceptions import ParseError
from westlake_survival.lib import search
from westlake_survival.lib.opac import CATALOG_API, OPAC_BASE, SEARCH_PATH

pytestmark = pytest.mark.live


def test_public_search_live() -> None:
    """真实公开检索。

    实测结论：``opac.westlake.edu.cn`` 为静态镜像，其 ``/opac/booklist.jsp``
    由 nginx 404；站点首页表单 action 所指的 ``172.16.10.223:8180/opac/booklist.jsp``
    同样 404（OPAC 应用上下文已下线）。因此公开检索当前不可用，``search()``
    抛 :class:`ParseError`；此时断言端点确实返回 404/403 以证明是端点问题而非
    解析器缺陷。若端点恢复，则断言返回非空书目。
    """
    try:
        books = search("机器学习")
    except ParseError:
        response = requests.post(
            OPAC_BASE + SEARCH_PATH,
            data={"searchtype": "title", "searchkey": "机器学习"},
            timeout=15,
        )
        assert response.status_code in (403, 404)
        return
    assert books


def test_catalog_api_requires_login() -> None:
    """门户检索 API 匿名访问被拒（401 需要先登录）——实测结论。"""
    response = requests.post(
        CATALOG_API + "/bolan-newbook/api/newbook/search/",
        json={"indexname": "newbook_batchbook", "newsearh": "机器学习"},
        timeout=15,
    )
    assert response.status_code == 401