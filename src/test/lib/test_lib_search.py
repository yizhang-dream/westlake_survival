"""opac 检索/详情/新书解析的离线测试。"""

from __future__ import annotations

import pytest

from _helpers import (
    BOOK_DETAIL_HTML,
    BOOKLIST_HTML,
    BOOKLIST_HTML_GBK,
    CATALOG_SEARCH_JSON,
    CATALOG_UNAUTHORIZED_JSON,
    NEW_BOOKS_HTML,
    OFFCAMPUS_HTML,
    FakeResponse,
    FakeSession,
)
from westlake_survival.exceptions import AuthError, OffCampusError, ParseError
from westlake_survival.lib import Book, book_detail, new_books, search, search_catalog


def test_search_parses_book_list() -> None:
    session = FakeSession(FakeResponse(BOOKLIST_HTML, url="http://opac/booklist.jsp"))
    books = search("机器学习", session=session)

    assert len(books) == 2
    first = books[0]
    assert isinstance(first, Book)
    assert first.title == "机器学习"
    assert first.author == "周志华"
    assert first.publisher == "清华大学出版社"
    assert first.publish_year == "2016"
    assert first.call_no == "TP181/Z68"
    assert first.isbn == "978-7-302-42328-7"
    assert first.location == "云谷校区"
    assert first.detail_url.endswith("/opac/bookdetail.jsp?bookid=1001")

    assert books[1].title == "深度学习"
    assert books[1].location == "云栖校区"

    # 请求确实打到 OPAC 检索端点，并带上 searchtype/searchkey
    method, url, kwargs = session.calls[0]
    assert method == "post"
    assert url.endswith("/booklist.jsp")
    assert kwargs["data"]["searchtype"] == "title"
    assert kwargs["data"]["searchkey"] == "机器学习"


def test_search_kind_maps_to_searchtype() -> None:
    session = FakeSession(FakeResponse(BOOKLIST_HTML))
    search("周志华", kind="author", session=session)
    assert session.calls[0][2]["data"]["searchtype"] == "author"


def test_search_gbk_page_decodes() -> None:
    response = FakeResponse(BOOKLIST_HTML_GBK, encoding="gb2312")
    books = search("数据库", session=FakeSession(response))

    assert len(books) == 1
    assert books[0].title == "数据库系统概论"
    assert books[0].author == "王珊"
    assert books[0].publisher == "高等教育出版社"
    assert books[0].location == "云谷校区"


def test_search_403_offcampus_raises() -> None:
    session = FakeSession(FakeResponse(OFFCAMPUS_HTML, status=403))
    with pytest.raises(OffCampusError):
        search("机器学习", session=session)


def test_search_404_raises_parse_error() -> None:
    session = FakeSession(FakeResponse("<html>404</html>", status=404))
    with pytest.raises(ParseError):
        search("机器学习", session=session)


def test_new_books_parses() -> None:
    session = FakeSession(FakeResponse(NEW_BOOKS_HTML))
    books = new_books(limit=10, session=session)

    assert len(books) == 1
    assert books[0].title == "人工智能导论"
    assert books[0].call_no == "TP18/L31"
    method, url, kwargs = session.calls[0]
    assert method == "get"
    assert url.endswith("/newbooklist.jsp")
    assert kwargs["params"] == {"target": 2}


def test_new_books_respects_limit() -> None:
    session = FakeSession(FakeResponse(BOOKLIST_HTML))
    assert len(new_books(limit=1, session=session)) == 1


def test_book_detail_fills_holding() -> None:
    book = Book(title="机器学习", detail_url="http://host/opac/bookdetail.jsp?bookid=1001")
    session = FakeSession(FakeResponse(BOOK_DETAIL_HTML))
    result = book_detail(book, session=session)

    assert result.location == "云谷校区"
    assert result.holding_status == "在馆"
    assert result.title == "机器学习"


def test_book_detail_without_url_is_noop() -> None:
    book = Book(title="无链接")
    assert book_detail(book) is book


def test_parse_catalog_books() -> None:
    session = FakeSession(FakeResponse(CATALOG_SEARCH_JSON))
    books = search_catalog("机器学习", session=session)

    assert len(books) == 1
    assert books[0].title == "机器学习"
    assert books[0].author == "周志华"
    assert books[0].call_no == "TP181/Z68"
    assert books[0].holding_status == "在馆"
    assert "/bookdetail?id=1001" in books[0].detail_url
    # 走 /headless 网关
    assert "/headless/bolan-newbook/api/newbook/search/" in session.calls[0][1]


def test_search_catalog_unauthorized_raises() -> None:
    session = FakeSession(FakeResponse(CATALOG_UNAUTHORIZED_JSON, status=401))
    with pytest.raises(AuthError):
        search_catalog("机器学习", session=session)