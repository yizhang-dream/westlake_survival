"""打印任务接口测试：`CloudPrint/Upload`、`PrintJob/Get|Del|PreviewPage`。

`PrintJob/Get` 的响应字段取自前端 `printDoc.js` 的解析口径（无账号无法实测），
其中 `szPaperDetail` 是**一段 JSON 字符串**，本库负责反序列化。
"""

from __future__ import annotations

import base64
import json

import pytest

from pms_fakes import TEST_BASE, FakeResponse, FakeSession, envelope

from westlake_survival.exceptions import NotFound
from westlake_survival.pms import PMSClient, PrintJob


class CapturingSession(FakeSession):
    """在请求发生的那一刻读走文件内容（句柄随后就被 with 关掉了）。"""

    def __init__(self, routes=None) -> None:
        super().__init__(routes)
        self.uploaded: bytes | None = None
        self.uploaded_name: str | None = None

    def request(self, method, url, **kwargs):  # type: ignore[override]
        files = kwargs.get("files") or {}
        entry = files.get("szPath")
        if entry:
            self.uploaded_name = entry[0]
            self.uploaded = entry[1].read()
        return super().request(method, url, **kwargs)

PRINT_JOBS = envelope(
    [
        {
            "dwJobId": 501,
            "szJobName": "论文终稿.pdf",
            "dwCopies": 2,
            "dwCreateDate": 20260922,
            "dwCreateTime": 100000,
            "dwDevSN": 1001,
            "szAttribe": "duplex;vdup;color;",
            "szPaperDetail": json.dumps(
                [{"dwPaperID": 9, "dwBWPages": 1, "dwColorPages": 2}]
            ),
        },
        {
            "dwJobId": 502,
            "szJobName": "作业.docx",
            "dwCopies": 1,
            "dwCreateDate": 20260921,
            "dwCreateTime": 93005,
            "dwDevSN": 1002,
            "szAttribe": "single;",
            "szPaperDetail": json.dumps([{"dwPaperID": 8, "dwBWPages": 3, "dwColorPages": 0}]),
        },
    ]
)


# --------------------------------------------------------------------------
# 上传 + 创建任务
# --------------------------------------------------------------------------


def test_upload_sends_multipart_fields(tmp_path):
    session = CapturingSession()
    session.add("/api/client/CloudPrint/Upload", FakeResponse(envelope()))
    client = PMSClient(session=session, base_url=TEST_BASE)
    target = tmp_path / "hw.pdf"
    target.write_bytes(b"%PDF-1.4 fake")

    client.upload(target, copies=3, paper_id=9, duplex=2, color=2, page_from=1, page_to=5)

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{TEST_BASE}/api/client/CloudPrint/Upload"
    assert call["data"] == {
        "dwPaperId": "9",
        "dwDuplex": "2",
        "dwColor": "2",
        "dwFrom": "1",
        "dwTo": "5",
        "dwCopies": "3",
        "BackURL": "",
    }
    # 文件字段名是 szPath（与前端表单同名），内容原样上传
    assert session.uploaded_name == "hw.pdf"
    assert session.uploaded == b"%PDF-1.4 fake"


def test_upload_defaults_use_paper_auto(client, session, tmp_path):
    session.add("/api/client/CloudPrint/Upload", FakeResponse(envelope()))
    target = tmp_path / "a.txt"
    target.write_text("hello", encoding="utf-8")
    client.upload(target)
    data = session.calls[0]["data"]
    assert data["dwPaperId"] == "-1"  # PAPER_AUTO
    assert data["dwDuplex"] == "1"
    assert data["dwColor"] == "1"
    assert data["dwCopies"] == "1"
    assert data["dwFrom"] == "0"
    assert data["dwTo"] == "0"
    assert "dwPdfImage" not in data


def test_upload_pdf_image_flag(client, session, tmp_path):
    session.add("/api/client/CloudPrint/Upload", FakeResponse(envelope()))
    target = tmp_path / "a.pdf"
    target.write_bytes(b"x")
    client.upload(target, pdf_image=True)
    assert session.calls[0]["data"]["dwPdfImage"] == "on"


def test_upload_page_from_zero_forces_page_to_zero(client, session, tmp_path):
    session.add("/api/client/CloudPrint/Upload", FakeResponse(envelope()))
    target = tmp_path / "a.pdf"
    target.write_bytes(b"x")
    client.upload(target, page_from=0, page_to=9)
    data = session.calls[0]["data"]
    assert data["dwFrom"] == "0"
    assert data["dwTo"] == "0"


def test_upload_missing_file(client, session, tmp_path):
    with pytest.raises(NotFound):
        client.upload(tmp_path / "nope.pdf")
    assert session.calls == []


def test_upload_surfaces_server_error(client, session, tmp_path):
    from westlake_survival.exceptions import ActionError

    session.add(
        "/api/client/CloudPrint/Upload",
        FakeResponse(envelope(None, code=2, message="文件过大上传失败")),
    )
    target = tmp_path / "big.pdf"
    target.write_bytes(b"x")
    with pytest.raises(ActionError) as excinfo:
        client.upload(target)
    assert "文件过大" in str(excinfo.value)


def test_create_print_job_is_passthrough(client, session):
    session.add("/api/client/PrintJob/Create", FakeResponse(envelope()))
    client.create_print_job({"szJobName": "a.pdf", "dwCopies": 1})
    call = session.calls[0]
    assert call["url"] == f"{TEST_BASE}/api/client/PrintJob/Create"
    assert call["json"] == {"szJobName": "a.pdf", "dwCopies": 1}


def test_set_print_job_is_passthrough(client, session):
    session.add("/api/client/PrintJob/Set", FakeResponse(envelope()))
    client.set_print_job(dwJobId=501, dwCopies=4)
    assert session.calls[0]["json"] == {"dwJobId": 501, "dwCopies": 4}


# --------------------------------------------------------------------------
# 任务列表 / 删除 / 预览
# --------------------------------------------------------------------------


def test_list_print_jobs_parses_sample(client, session):
    session.add("/api/client/PrintJob/Get", FakeResponse(PRINT_JOBS))
    jobs = client.list_print_jobs()

    assert [job.id for job in jobs] == [501, 502]
    first = jobs[0]
    assert isinstance(first, PrintJob)
    assert first.name == "论文终稿.pdf"
    assert first.copies == 2
    assert first.dev_sn == 1001
    assert first.paper_detail == [{"dwPaperID": 9, "dwBWPages": 1, "dwColorPages": 2}]
    assert first.total_pages == 3
    assert first.is_color is True
    assert first.duplex == "vdup"
    assert first.created_at is not None
    assert first.created_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-22 10:00:00"

    second = jobs[1]
    assert second.duplex == "single"
    assert second.is_color is False
    assert second.total_pages == 3
    assert second.created_at.strftime("%H:%M:%S") == "09:30:05"

    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == f"{TEST_BASE}/api/client/PrintJob/Get"


def test_list_print_jobs_empty(client, session):
    session.add("/api/client/PrintJob/Get", FakeResponse(envelope(None)))
    assert client.list_print_jobs() == []


def test_list_print_jobs_by_dev_sn(client, session):
    session.add("/api/client/PrintJob/GetByDevSN", FakeResponse(PRINT_JOBS))
    client.list_print_jobs(dev_sn=1001)
    assert session.calls[0]["params"] == {"dwDevSN": 1001}


def test_delete_print_job_body(client, session):
    session.add("/api/client/PrintJob/Del", FakeResponse(envelope()))
    client.delete_print_job(501)
    assert session.calls[0]["json"] == {"dwJobId": 501, "dwOldJobId": 501}


def test_delete_print_job_with_old_id(client, session):
    session.add("/api/client/PrintJob/Del", FakeResponse(envelope()))
    client.delete_print_job(501, 999)
    assert session.calls[0]["json"] == {"dwJobId": 501, "dwOldJobId": 999}


def test_preview_page_decodes_base64(client, session):
    raw = b"\x89PNG\r\n\x1a\n fake"
    session.add(
        "/api/client/PrintJob/PreviewPage",
        FakeResponse(envelope(base64.b64encode(raw).decode("ascii"))),
    )
    assert client.preview_page(501, 20260922100000, page_no=2) == raw
    params = session.calls[0]["params"]
    assert params == {"dwJobId": 501, "dwCreateTime": 20260922100000, "pageNo": 2}


def test_preview_page_bad_result_type(client, session):
    from westlake_survival.exceptions import ParseError

    session.add("/api/client/PrintJob/PreviewPage", FakeResponse(envelope(123)))
    with pytest.raises(ParseError):
        client.preview_page(501, 1)


def test_take_out_is_optional_params(client, session):
    session.add("/api/client/PrintJob/TakeOut", FakeResponse(envelope({"ok": True})))
    client.take_out()
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0].get("params") in (None, {})
