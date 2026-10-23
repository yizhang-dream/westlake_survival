"""校园地图模块端到端测试：真实抓官网 → 解析 → 数据模型 → 图片可达。

默认被 ``-m 'not live'`` 排除；真实验证：
``pytest src/test/campusmap/test_campusmap_e2e.py -q -m live``。
"""

from __future__ import annotations

import pytest
import requests

from westlake_survival.campusmap import CAMPUS_NAMES, campus_map


@pytest.mark.live
def test_live_three_campuses_with_map_and_panorama() -> None:
    """三校区齐全；云谷与云栖有地图与全景，铜鉴湖两者皆无（官网现状）。"""
    items = campus_map()

    assert [item.name for item in items] == list(CAMPUS_NAMES)
    by_name = {item.name: item for item in items}

    for name in ("云谷", "云栖"):
        assert by_name[name].address
        assert by_name[name].postcode
        assert by_name[name].map_url and by_name[name].map_url.startswith("https://")
        assert len(by_name[name].panoramas) == 1
        assert "720yun.com" in by_name[name].panoramas[0].url

    assert by_name["铜鉴湖"].map_url is None
    assert by_name["铜鉴湖"].panoramas == []
    assert by_name["铜鉴湖"].address


@pytest.mark.live
def test_live_traffic_includes_metro_and_bus_hours() -> None:
    """到校交通含自驾路径与地铁/公交首末班时间。"""
    yungu = next(item for item in campus_map("云谷") if item.name == "云谷")

    joined = "\n".join(yungu.traffic)
    assert "自驾" in joined
    assert "地铁" in joined and "首班车" in joined
    assert "公交" in joined


@pytest.mark.live
def test_live_campus_filter_and_unknown() -> None:
    """子串过滤生效；未知校区立即报错。"""
    assert [item.name for item in campus_map("铜鉴湖")] == ["铜鉴湖"]
    with pytest.raises(ValueError):
        campus_map("火星")


@pytest.mark.live
def test_live_map_images_reachable() -> None:
    """地图图片是真实可打开的 PNG（核对最终产物，不只看 URL 字符串）。"""
    for item in campus_map():
        if not item.map_url:
            continue
        response = requests.get(item.map_url, timeout=30, stream=True)
        try:
            assert response.status_code == 200, item.name
            assert response.headers.get("Content-Type", "").startswith("image/")
            head = b""
            for chunk in response.iter_content(16):
                head += chunk
                if len(head) >= 8:
                    break
            assert head[:4] == bytes([0x89, 0x50, 0x4E, 0x47]), item.name
        finally:
            response.close()
