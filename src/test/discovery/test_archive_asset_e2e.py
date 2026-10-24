"""清扫批新发现方法端到端：Wayback 历史索引 + 静态资产收割 + 词表覆盖。

离线用例校验词表与注册表一致性；在线用例（``-m live``）真拉 Wayback CDX。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from westlake_survival.discovery import CENSUS_HOSTS


def test_census_hosts_cover_sweep_batch_hits_offline() -> None:
    """2026-10-24 大字典清扫批命中的新站全部进词表（复扫可达）。"""
    must = {
        "2dmater", "aging-conference", "astro", "audio", "bioinfo", "cap",
        "car", "career", "mp", "pan", "report", "storage", "visitor",
        "idp", "1x", "cbis",
    }
    assert must <= set(CENSUS_HOSTS)


def test_registry_rows_match_new_services_offline() -> None:
    """清扫批新站全部登记进服务注册表（/services 一主机一行）。"""
    source = Path(__file__).parents[2] / "westlake_survival" / "discovery.py"
    rows = set(re.findall(r'\("([a-z0-9.-]+)",\s*"[^"]*",\s*"[^"]*"\)',
                          source.read_text(encoding="utf-8")))
    must = {
        "2dmater", "aging-conference", "astro", "audio", "bioinfo", "cap",
        "car", "career", "cbis", "eer.lab", "mp", "pan", "report", "storage",
        "visitor", "webvpn2", "1x", "idp",
    }
    assert must <= rows, sorted(must - rows)


@pytest.mark.live
def test_live_archive_hosts_wayback() -> None:
    from westlake_survival.discovery import archive_hosts

    hosts = archive_hosts()
    assert isinstance(hosts, dict)
    assert len(hosts) >= 5  # 历史索引至少覆盖几个已知子域
    assert any("www" == h for h in hosts)
