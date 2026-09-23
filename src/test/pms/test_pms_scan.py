"""扫描任务接口测试：`Scan/Get|Del|Download`。

字段取自前端 `scanDoc.html`（模板 + 下载链接）。
"""

from __future__ import annotations

from pms_fakes import TEST_BASE, FakeResponse, envelope

from westlake_survival.pms import ScanJob

SCAN_JOBS = envelope(
    [
        {
            "dwJobId": 9001,
            "szDisplayName": "扫描件_20260922.pdf",
            "szFileName": "scan9001.pdf",
            "dwFileSize": 204800,
            "dwSubmitDate": 20260922,
            "dwSubmitTime": 141530,
            "dwStatus": 1,
        },
        {
            "dwJobId": 9002,
            "szDisplayName": "notes.jpg",
            "dwFileSize": 512,
            "dwSubmitDate": 20260922,
            "dwSubmitTime": 90000,
            "dwStatus": 257,  # 位 256 置位：前端视作不可下载
        },
    ]
)


def test_list_scan_jobs_parses_sample(client, session):
    session.add("/api/client/Scan/Get", FakeResponse(SCAN_JOBS))
    jobs = client.list_scan_jobs()

    assert [job.id for job in jobs] == [9001, 9002]
    first = jobs[0]
    assert isinstance(first, ScanJob)
    assert first.display_name == "扫描件_20260922.pdf"
    assert first.file_name == "scan9001.pdf"
    assert first.file_size == 204800
    assert first.submitted_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-22 14:15:30"

    second = jobs[1]
    assert second.file_name == "notes.jpg"  # szFileName 缺失时回退 szDisplayName
    assert second.status == 257
    assert second.status & 256

    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == f"{TEST_BASE}/api/client/Scan/Get"


def test_list_scan_jobs_empty(client, session):
    session.add("/api/client/Scan/Get", FakeResponse(envelope([])))
    assert client.list_scan_jobs() == []


def test_delete_scan_job_body(client, session):
    session.add("/api/client/Scan/Del", FakeResponse(envelope()))
    client.delete_scan_job(9001)
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["json"] == {"dwJobId": 9001}


def test_set_scan_job_passthrough(client, session):
    session.add("/api/client/Scan/Set", FakeResponse(envelope()))
    client.set_scan_job(dwJobId=9001, szDisplayName="renamed.pdf")
    assert session.calls[0]["json"] == {"dwJobId": 9001, "szDisplayName": "renamed.pdf"}


def test_download_scan_streams_to_disk(client, session, tmp_path):
    body = b"%PDF-1.4 scanned" * 3
    session.add(
        "/api/client/Scan/Download",
        FakeResponse(
            status_code=200,
            text="",
            headers={"Content-Type": "application/pdf"},
            chunks=[body[:8], body[8:]],
        ),
    )
    dest = tmp_path / "out" / "scan.pdf"
    result = client.download_scan(9001, dest, additional=141530)

    assert result == dest
    assert dest.read_bytes() == body
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["params"] == {"dwJobId": 9001, "dwAdditional": 141530}
    assert call["stream"] is True


def test_download_scan_without_additional(client, session, tmp_path):
    session.add(
        "/api/client/Scan/Download",
        FakeResponse(status_code=200, text="", chunks=[b"x"]),
    )
    client.download_scan(9001, tmp_path / "a.bin")
    assert session.calls[0]["params"] == {"dwJobId": 9001}


def test_download_scan_http_error(client, session, tmp_path):
    import pytest

    from westlake_survival.exceptions import ActionError, WestlakeError

    session.add(
        "/api/client/Scan/Download",
        FakeResponse(status_code=500, text="boom"),
    )
    with pytest.raises(WestlakeError):
        client.download_scan(9001, tmp_path / "a.bin")
    assert isinstance(ActionError("x"), WestlakeError)  # 同为库异常族
