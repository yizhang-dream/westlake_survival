"""学术资源模块端到端测试：注册表 / CARSI 目录快照 / DOI 解析与 PDF / 页面。

离线用例（默认跑）：只依赖随包数据，不发网络请求。
在线用例（``-m live``）：真实探测校园 IP 信标、CrossRef/OpenAlex、出版社
PDF 通道与 WebUI 页面。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.scholar import (
    DATABASES,
    IDP_ENTITY_ID,
    carsi_catalog,
    carsi_sso_entry,
    databases,
    normalize_doi,
)


# --------------------------------------------------------------------------- #
# 离线：注册表与入口构造
# --------------------------------------------------------------------------- #
def test_registry_keys_unique_and_fields_complete() -> None:
    keys = [db.key for db in DATABASES]
    assert len(keys) == len(set(keys))
    for db in DATABASES:
        assert db.name and db.url.startswith("https://")
        assert db.access in {"campus", "carsi", "open", "account"}
        assert db.category
    # 核心库必须在位：中文全文 + 引文索引 + 数据平台
    by_key = {db.key: db for db in DATABASES}
    assert by_key["cnki"].access == "carsi"
    assert by_key["heqdata"].category == "数据平台"
    assert "wos" in by_key and "sciencedirect" in by_key


def test_databases_filter_by_keyword() -> None:
    assert databases("知网") and databases("知网")[0].key == "cnki"
    assert all("外文" in db.category for db in databases("外文全文"))


def test_carsi_sso_entry_uses_school_idp() -> None:
    entry = carsi_sso_entry("cnki")
    assert "fsso.cnki.net/Shibboleth.sso/Login" in entry
    assert IDP_ENTITY_ID.replace("/", "%2F").replace(":", "%3A") in entry
    # 通用 Shibboleth SP：https URL → <host>/Shibboleth.sso/Login
    generic = carsi_sso_entry("https://link.springer.com/journal/1")
    assert generic.startswith("https://link.springer.com/Shibboleth.sso/Login?entityID=")


def test_normalize_doi_strips_prefixes() -> None:
    assert normalize_doi("https://doi.org/10.1/x") == "10.1/x"
    assert normalize_doi("doi:10.1/x") == "10.1/x"
    assert normalize_doi(" 10.1/x ") == "10.1/x"


# --------------------------------------------------------------------------- #
# 离线：CARSI 目录随包快照
# --------------------------------------------------------------------------- #
def test_carsi_catalog_fixture_offline() -> None:
    sps = carsi_catalog()
    assert len(sps) >= 300  # 2026-10-24 快照 356 个
    names = " ".join(str(s.get("production") or "") for s in sps)
    for must in ("中国知网", "Web of Science", "IEEE"):
        assert must in names


def test_carsi_catalog_query_filter_offline() -> None:
    hits = carsi_catalog("知网")
    assert hits and all("知网" in str(s.get("production") or "") for s in hits)


def test_carsi_fixture_has_source_attribution() -> None:
    fixture = Path(__file__).parents[2] / "westlake_survival" / "data" / "carsi_sps.json"
    import json

    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["source"].startswith("https://www.carsi.edu.cn/")
    assert payload["count"] == len(payload["sps"])
    assert len(payload["sps"]) >= 300


# --------------------------------------------------------------------------- #
# 离线：citation_pdf_url 元标签解析
# --------------------------------------------------------------------------- #
def test_publisher_pdf_url_meta_parsing_offline() -> None:
    from westlake_survival.scholar import _publisher_pdf_url

    class FakeResponse:
        status_code = 200
        text = ('<head><meta name="citation_pdf_url" '
                'content="/content/pdf/10.1/x.pdf"></head>')
        url = "https://example.org/article"

    class FakeSession:
        def get(self, *a, **kw):
            return FakeResponse()

    url = _publisher_pdf_url(FakeSession(), "https://doi.org/10.1/x")
    assert url == "https://example.org/content/pdf/10.1/x.pdf"


def test_mcp_tools_registered() -> None:
    from westlake_survival.mcp_server import list_tools

    names = {spec["name"] for spec in list_tools()}
    assert {"scholar_databases", "scholar_resolve_doi", "scholar_campus"} <= names


# --------------------------------------------------------------------------- #
# 在线：校园信标 / DOI 解析 / PDF 下载 / CLI / WebUI
# --------------------------------------------------------------------------- #
@pytest.mark.live
def test_live_campus_status_beacon() -> None:
    from westlake_survival.scholar import campus_status

    status = campus_status(refresh=True)
    assert status.checked_at
    assert "信标" in status.evidence  # 探测本身完成（命中与否取决于所在网络）


@pytest.mark.live
def test_live_resolve_doi_crossref_and_pdf_url() -> None:
    from westlake_survival.scholar import resolve_doi

    paper = resolve_doi("10.1007/s00453-018-0477-7")
    assert "Solving Problems" in paper.title
    assert paper.year == "2018"
    assert paper.publisher
    assert paper.publisher_pdf_url.endswith(".pdf")


@pytest.mark.live
def test_live_fetch_pdf_magic_bytes(tmp_path) -> None:
    from westlake_survival.scholar import fetch_pdf

    out = tmp_path / "paper.pdf"
    path = fetch_pdf("10.1007/s00453-018-0477-7", out)
    data = path.read_bytes()
    assert data[:5] == b"%PDF-" and len(data) > 10000


@pytest.mark.live
def test_live_cli_scholar_dbs_and_campus() -> None:
    from click.testing import CliRunner

    from westlake_survival.scholar import cli_group

    result = CliRunner().invoke(cli_group, ["dbs", "-k", "知网"])
    assert result.exit_code == 0 and "中国知网" in result.output

    result = CliRunner().invoke(cli_group, ["campus"])
    assert result.exit_code == 0 and "校园网" in result.output


@pytest.mark.live
def test_live_webui_scholar_page() -> None:
    from westlake_survival.webui.app import create_app

    client = create_app().test_client()
    page = client.get("/scholar")
    assert page.status_code == 200
    assert "中国知网".encode() in page.data
    api = client.get("/api/scholar/doi?doi=10.1007/s00453-018-0477-7")
    assert api.status_code == 200
    assert "Solving Problems" in api.get_json()["title"]
