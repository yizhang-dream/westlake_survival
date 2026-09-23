"""消费/用量接口测试：`Report/Stat`、`Report/DetailPage`。

请求字段取自前端 `entry.js`（首页累计用量）与 `footprint.js`（足迹分页）。
"""

from __future__ import annotations

from pms_fakes import TEST_BASE, FakeResponse, envelope

from westlake_survival.pms import UsageRecord, UsageSummary

STAT_ROWS = envelope(
    [
        {
            "dwType": 1,
            "dwUseTimes": 12,
            "dwPages": 96,
            "dwUsedCardMoney": 1200,
            "dwUsedFreeMoney": 300,
            "dwUsedMoney": 0,
        },
        {
            "dwType": 3,
            "dwUseTimes": 2,
            "dwPages": 4,
            "dwUsedCardMoney": 0,
            "dwUsedFreeMoney": 0,
            "dwUsedMoney": 40,
        },
    ]
)

DETAIL_PAGE = {
    "code": 0,
    "message": "",
    "result": [
        {
            "dwDate": 20260922,
            "dwTime": 101500,
            "dwType": 1,
            "dwPages": 3,
            "dwCopies": 1,
            "dwPaperID": 9,
            "dwUsedCardMoney": 30,
            "dwUsedFreeMoney": 20,
            "dwUsedMoney": 0,
            "dwSettleType": 0,
            "dwJobId": 501,
            "szJobName": "论文终稿.pdf",
        },
        {
            "dwDate": 20260921,
            "dwTime": 93000,
            "dwType": 1,
            "dwPages": 1,
            "dwPaperID": 8,
            "dwUsedCardMoney": 20,
            "dwUsedFreeMoney": 0,
            "dwUsedMoney": 0,
            "dwSettleType": 4,
        },
    ],
    "dwTotalPage": 3,
    "dwTotalCount": 25,
}


# --------------------------------------------------------------------------
# Report/Stat
# --------------------------------------------------------------------------


def test_usage_stat_request_body_and_parse(client, session):
    session.add("/api/client/Report/Stat", FakeResponse(STAT_ROWS))
    rows = client.usage_stat()

    assert len(rows) == 2
    first = rows[0]
    assert isinstance(first, UsageSummary)
    assert first.type == 1
    assert first.times == 12
    assert first.pages == 96
    assert first.cost == 15.0  # (1200 + 300)/100

    call = session.calls[0]
    assert call["url"] == f"{TEST_BASE}/api/client/Report/Stat"
    assert call["json"] == {"dwBeginDate": "0", "dwEndDate": "99999999"}


def test_usage_stat_custom_range(client, session):
    session.add("/api/client/Report/Stat", FakeResponse(envelope(None)))
    assert client.usage_stat("20260101", "20261231") == []
    assert session.calls[0]["json"] == {"dwBeginDate": "20260101", "dwEndDate": "20261231"}


# --------------------------------------------------------------------------
# Report/DetailPage
# --------------------------------------------------------------------------


def test_usage_records_request_body_and_parse(client, session):
    session.add("/api/client/Report/DetailPage", FakeResponse(DETAIL_PAGE))
    page = client.usage_records("20260901", "20260930", type=1, page_no=1, row_count=10)

    assert page.total_page == 3
    assert page.total_count == 25
    assert len(page.records) == 2

    first = page.records[0]
    assert isinstance(first, UsageRecord)
    assert first.type == 1
    assert first.pages == 3
    assert first.copies == 1
    assert first.paper == "A4"
    assert first.job_id == 501
    assert first.name == "论文终稿.pdf"
    assert first.cost == 0.5  # (30+20+0)/100
    assert first.time_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-22 10:15:00"

    second = page.records[1]
    assert second.paper == "A3"
    assert second.cost == 0.2
    assert second.settle_type == 4  # 前端据此判定「手工收费」

    call = session.calls[0]
    assert call["url"] == f"{TEST_BASE}/api/client/Report/DetailPage"
    assert call["json"] == {
        "dwBeginDate": "20260901",
        "dwEndDate": "20260930",
        "dwType": 1,
        "dwPageNo": 1,
        "dwRowCount": 10,
    }


def test_usage_records_defaults(client, session):
    session.add("/api/client/Report/DetailPage", FakeResponse(DETAIL_PAGE))
    client.usage_records()
    assert session.calls[0]["json"] == {
        "dwBeginDate": "0",
        "dwEndDate": "99999999",
        "dwType": 1,
        "dwPageNo": 1,
        "dwRowCount": 10,
    }


def test_usage_records_accepts_bare_list(client, session):
    session.add("/api/client/Report/DetailPage", FakeResponse(envelope([{"dwPages": 1}])))
    page = client.usage_records()
    assert page.total_page is None
    assert page.records[0].pages == 1


def test_usage_records_missing_result(client, session):
    session.add("/api/client/Report/DetailPage", FakeResponse(envelope(None)))
    page = client.usage_records()
    assert page.records == []


def test_report_passthrough_methods(client, session):
    session.add("/api/client/Report/Detail", FakeResponse(envelope({"ok": 1})))
    session.add("/api/client/Report/InvoicePage", FakeResponse(envelope({"ok": 2})))
    session.add("/api/client/Report/DoInvoice", FakeResponse(envelope({"ok": 3})))
    assert client.usage_detail({"dwType": 1})["ok"] == 1
    assert client.invoice_page({"dwPageNo": 1})["ok"] == 2
    assert client.make_invoice({"dwApply": 1})["ok"] == 3
