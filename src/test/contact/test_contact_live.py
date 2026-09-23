"""真实网络测试：需要能访问官网（默认被 ``-m 'not live'`` 排除）。

运行：``pytest src/test/contact -q -m live``
"""

from __future__ import annotations

import pytest

from westlake_survival.contact import CAMPUS_NAMES, campuses, contacts


@pytest.mark.live
def test_live_campuses_and_contacts() -> None:
    """真抓「联系我们」页：应解析出三校区地址与招生电话/邮箱。"""
    infos = campuses()

    assert len(infos) >= 3
    names = [c.name for c in infos]
    for expected in CAMPUS_NAMES:
        assert expected in names

    yungu = next(c for c in infos if c.name == "云谷")
    assert "墩余路" in yungu.address
    assert yungu.postcode
    assert yungu.map_url and yungu.map_url.startswith("https://")

    entries = contacts()
    assert entries
    admissions = next(c for c in entries if "招生" in c.label)
    assert any(p.startswith("0571-") for p in admissions.phones)
    assert any(e.endswith("@westlake.edu.cn") for e in admissions.emails)
