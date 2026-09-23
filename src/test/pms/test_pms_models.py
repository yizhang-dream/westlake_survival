"""模型层容错测试：缺字段 / None / 脏类型 / 时间与金额换算。"""

from __future__ import annotations

from datetime import datetime

from westlake_survival.pms import (
    PrintJob,
    ScanJob,
    Station,
    UsageRecord,
    UsageSummary,
)
from westlake_survival.pms.models import (
    CHINA_TZ,
    Paper,
    parse_epoch,
    parse_packed_datetime,
    parse_paper_detail,
    paper_name,
)


def test_from_json_tolerates_empty_inputs():
    for cls in (Station, PrintJob, ScanJob, UsageRecord, UsageSummary, Paper):
        obj = cls.from_json(None)
        assert obj is not None
        obj = cls.from_json("not-a-dict")
        assert obj is not None
        obj = cls.from_json({})
        assert obj is not None


def test_from_json_tolerates_missing_fields():
    job = PrintJob.from_json({"dwJobId": 1})
    assert job.id == 1
    assert job.name is None
    assert job.copies is None
    assert job.paper_detail == []
    assert job.created_at is None
    assert job.total_pages == 0
    assert job.duplex is None
    assert job.is_color is False


def test_from_json_coerces_string_numbers():
    station = Station.from_json({"dwDevSN": "1001", "dwProperty": "95", "dwTrayPaper1": "9"})
    assert station.dev_sn == 1001
    assert station.capabilities == 95
    assert station.supports_color is True
    assert station.papers == ["A4"]


def test_parse_packed_datetime():
    value = parse_packed_datetime(20260922, 100000)
    assert value == datetime(2026, 9, 22, 10, 0, 0, tzinfo=CHINA_TZ)
    # 位数不足左侧补零（前端 fommateTimeToHHMM 口径）
    assert parse_packed_datetime(20260922, 70000) == datetime(
        2026, 9, 22, 7, 0, 0, tzinfo=CHINA_TZ
    )
    assert parse_packed_datetime(20260922, None) == datetime(
        2026, 9, 22, 0, 0, 0, tzinfo=CHINA_TZ
    )
    assert parse_packed_datetime(0, 100000) is None
    assert parse_packed_datetime(None, None) is None
    assert parse_packed_datetime(20261399, 0) is None  # 非法月日
    assert parse_packed_datetime("20260922", "101500") == datetime(
        2026, 9, 22, 10, 15, 0, tzinfo=CHINA_TZ
    )


def test_parse_epoch():
    value = parse_epoch(1790014224)
    assert value is not None and value.tzinfo is not None
    assert value.year == 2026
    assert parse_epoch(0) is None
    assert parse_epoch(None) is None
    assert parse_epoch("bogus") is None


def test_parse_paper_detail_variants():
    assert parse_paper_detail(None) == []
    assert parse_paper_detail("") == []
    assert parse_paper_detail("not json") == []
    assert parse_paper_detail('[{"dwPaperID":9}]') == [{"dwPaperID": 9}]
    assert parse_paper_detail([{"a": 1}, "junk", None]) == [{"a": 1}]
    assert parse_paper_detail({"a": 1}) == [{"a": 1}]


def test_paper_name_mapping():
    assert paper_name(9) == "A4"
    assert paper_name(8) == "A3"
    assert paper_name(0) is None
    assert paper_name(None) is None
    assert paper_name(123) == "123"


def test_print_job_paper_detail_totals():
    job = PrintJob.from_json(
        {
            "dwJobId": 1,
            "szPaperDetail": (
                '[{"dwPaperID":9,"dwBWPages":2,"dwColorPages":1},'
                '{"dwPaperID":8,"dwBWPages":5,"dwColorPages":0}]'
            ),
        }
    )
    assert len(job.paper_detail) == 2
    assert job.total_pages == 8


def test_print_job_duplex_variants():
    assert PrintJob.from_json({"szAttribe": "single;"}).duplex == "single"
    assert PrintJob.from_json({"szAttribe": "vdup;color"}).duplex == "vdup"
    assert PrintJob.from_json({"szAttribe": "vdup_short;color"}).duplex == "vdup_short"
    assert PrintJob.from_json({"szAttribe": "duplex"}).duplex == "unknown"
    assert PrintJob.from_json({"szAttribe": "duplex;color"}).is_color is True
    assert PrintJob.from_json({"szAttribe": "single"}).is_color is False


def test_print_job_duplex_judgement_order():
    """锁定判序：``vdup_short`` 含子串 ``vdup``，必须先判短边再判长边。"""
    assert PrintJob.from_json({"szAttribe": "vdup_short"}).duplex == "vdup_short"
    assert PrintJob.from_json({"szAttribe": "VDUP_SHORT;"}).duplex == "vdup_short"
    assert PrintJob.from_json({"szAttribe": "vdup"}).duplex == "vdup"
    # 同时含 single 时 single 优先（前端 attribute 串以分号分隔，单面不含 vdup）
    assert PrintJob.from_json({"szAttribe": "single;vdup_short"}).duplex == "single"
    # 无任何单双面关键字：中性值，不再兜底误判
    assert PrintJob.from_json({"szAttribe": "color"}).duplex == "unknown"


def test_print_job_field_aliases():
    """spec 里提到的 filename / color 以只读别名形式提供。"""
    job = PrintJob.from_json({"szJobName": "a.pdf", "szAttribe": "color"})
    assert job.filename == "a.pdf"
    assert job.name == "a.pdf"
    assert job.color is True


def test_scan_job_time():
    job = ScanJob.from_json({"dwJobId": 1, "dwSubmitDate": 20260922, "dwSubmitTime": 141530})
    assert job.submitted_at.strftime("%H:%M:%S") == "14:15:30"


def test_usage_record_cost_and_paper():
    record = UsageRecord.from_json(
        {"dwUsedCardMoney": 30, "dwUsedFreeMoney": 20, "dwUsedMoney": 5, "dwPaperID": 9}
    )
    assert record.cost == 0.55
    assert record.cost_yuan == 0.55
    assert record.paper == "A4"


def test_station_papers_order_and_status():
    station = Station.from_json({"dwTrayPaper1": 8, "dwTrayPaper2": 9, "dwStatus": 2})
    assert station.papers == ["A3", "A4"]
    assert station.is_busy is True
    assert station.is_idle is False
    assert Station.from_json({"dwStatus": 0}).is_disabled is True


def test_paper_units():
    paper = Paper.from_json({"dwPaperID": 9, "dwWidth": 21000, "dwHeight": 29700})
    assert paper.width_mm == 210.0
    assert paper.height_mm == 297.0
