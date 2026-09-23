"""网点与纸型接口测试（`Station/*`、`Paper/*`）。

样本取自 2026-09-22 校内实测的 `Station/GetList` / `Paper/GetPaper` 原始响应。
"""

from __future__ import annotations

import json

from pms_fakes import TEST_BASE, FakeResponse, envelope

from westlake_survival.pms import Station

STATION_PAYLOAD = {
    "code": 0,
    "message": "",
    "result": [
        {
            "dwDevSN": 1001,
            "dwFunction": 7,
            "dwCtrlType": 1,
            "dwProperty": 95,
            "dwStatus": 1,
            "dwKind": 0,
            "dwTrayPaper1": 9,
            "dwTrayPaper2": 8,
            "dwTrayPaper3": 0,
            "dwTrayPaper4": 0,
            "dwModel": 102,
            "dwSpeed": 0,
            "dwOpenTime": 0,
            "dwCloseTime": 1439,
            "dwChgTime": 1789960325,
            "dwUpdateTime": 1790014224,
            "szName": "云栖图书馆彩色",
            "szIP": "172.16.53.220",
            "szPosition": "",
            "szTel": "",
            "szCardIP": "",
            "szMAC": "68eda43bb69e",
            "szCampus": "",
            "szRoomName": "",
            "szDeptName": "",
            "szPrtDriver": "FX DocuCentre-V C2265 PCL 6",
            "szStatInfo": "系统空闲",
            "szMemo": "",
        },
        {
            "dwDevSN": 1002,
            "dwProperty": 87,
            "dwStatus": 1,
            "dwTrayPaper1": 9,
            "dwTrayPaper2": 8,
            "szName": "云栖图书馆黑白",
            "szIP": "172.16.53.128",
            "szStatInfo": "系统空闲",
        },
        {
            "dwDevSN": 1003,
            "dwProperty": 119,
            "dwStatus": 513,
            "dwTrayPaper1": 9,
            "dwTrayPaper2": 8,
            "szName": "云谷图书馆黑白",
            "szStatInfo": "A4纸已快用完",
        },
        {
            "dwDevSN": 1004,
            "dwProperty": 127,
            "dwStatus": 1,
            "dwTrayPaper1": 9,
            "dwTrayPaper2": 8,
            "szName": "云谷图书馆彩色",
            "szStatInfo": "系统空闲",
        },
    ],
}


def test_list_stations_parses_real_sample(client, session):
    session.add("/api/client/Station/GetList", FakeResponse(STATION_PAYLOAD))
    stations = client.list_stations()

    assert len(stations) == 4
    assert all(isinstance(s, Station) for s in stations)
    first = stations[0]
    assert first.dev_sn == 1001
    assert first.name == "云栖图书馆彩色"
    assert first.ip == "172.16.53.220"
    assert first.status_text == "系统空闲"
    assert first.printer_driver == "FX DocuCentre-V C2265 PCL 6"
    assert first.mac == "68eda43bb69e"
    assert first.open_time == 0
    assert first.close_time == 1439
    assert first.trays == [9, 8]
    assert first.papers == ["A3", "A4"]
    assert first.updated_at is not None and first.updated_at.year == 2026

    # 请求方法/路径
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == f"{TEST_BASE}/api/client/Station/GetList"


def test_station_status_and_property_bitmaps(client, session):
    session.add("/api/client/Station/GetList", FakeResponse(STATION_PAYLOAD))
    by_sn = {s.dev_sn: s for s in client.list_stations()}

    color = by_sn[1001]
    assert color.supports_print and color.supports_copy and color.supports_scan
    assert color.supports_color is True

    mono = by_sn[1002]
    assert mono.supports_print is True
    assert mono.supports_color is False  # dwProperty=87，无 0x08 位

    warning = by_sn[1003]
    assert warning.is_idle is True  # 513 & 0x1
    assert warning.is_busy is False
    assert warning.status_text == "A4纸已快用完"


def test_list_stations_empty(client, session):
    session.add("/api/client/Station/GetList", FakeResponse(envelope(None)))
    assert client.list_stations() == []


def test_list_servers(client, session):
    session.add(
        "/api/client/Station/GetSrvList",
        FakeResponse(envelope([{"dwSN": 1, "szName": "OPMServer", "szIP": "172.16.10.222"}])),
    )
    servers = client.list_servers()
    assert servers[0]["szName"] == "OPMServer"


def test_get_station(client, session):
    session.add(
        "/api/client/Station/GetByDevSN",
        FakeResponse(envelope({"dwDevSN": 1002, "szName": "云栖图书馆黑白"})),
    )
    station = client.get_station(1002)
    assert station.dev_sn == 1002
    assert session.calls[0]["params"] == {"dwDevSN": 1002}


# --------------------------------------------------------------------------
# 纸型
# --------------------------------------------------------------------------

PAPER_PAYLOAD = envelope(
    [
        {
            "dwPaperID": 8,
            "dwWidth": 29700,
            "dwHeight": 42000,
            "dwStatus": 1,
            "dwTrayIndex": 0,
            "szPaperName": "A3",
        },
        {
            "dwPaperID": 9,
            "dwWidth": 21000,
            "dwHeight": 29700,
            "dwStatus": 1,
            "dwTrayIndex": 0,
            "szPaperName": "A4",
        },
        {
            "dwPaperID": 123,
            "dwWidth": 84100,
            "dwHeight": 118890,
            "dwStatus": 1,
            "dwTrayIndex": 0,
            "szPaperName": "A0",
        },
    ]
)


def test_list_papers(client, session):
    session.add("/api/client/Paper/GetPaper", FakeResponse(PAPER_PAYLOAD))
    papers = client.list_papers()
    assert [p.name for p in papers] == ["A3", "A4", "A0"]
    a4 = papers[1]
    assert a4.id == 9
    # 服务端单位 0.1mm → mm
    assert a4.width_mm == 210.0
    assert a4.height_mm == 297.0
    assert session.calls[0]["url"] == f"{TEST_BASE}/api/client/Paper/GetPaper"


def test_list_papers_empty(client, session):
    session.add("/api/client/Paper/GetPaper", FakeResponse(envelope([])))
    assert client.list_papers() == []


def test_fee_standards(client, session):
    session.add(
        "/api/client/PrintJob/GetCurrentUserFeeStd",
        FakeResponse(envelope([{"dwFeeItemSN": 1, "dwFee": 10, "szFeeItemName": "黑白A4"}])),
    )
    items = client.fee_standards(1)
    assert items[0]["szFeeItemName"] == "黑白A4"
    assert session.calls[0]["params"] == {"dwFeeItemSN": 1}


def test_fee_standard_post_passthrough(client, session):
    session.add("/api/client/FeeStd/Get", FakeResponse(envelope([])))
    client.fee_standard({"dwType": 1})
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["json"] == {"dwType": 1}


def test_models_module_is_exported():
    """Station.from_json 对脏数据不抛异常。"""
    assert Station.from_json(None).dev_sn is None
    assert Station.from_json({"dwTrayPaper1": "9"}).papers == ["A4"]
    assert Station.from_json(json.loads("{}")).papers == []
