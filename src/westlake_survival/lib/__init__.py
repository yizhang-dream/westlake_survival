"""图书馆模块：OPAC 书目检索、新书推荐与个人借阅。

公开用法::

    from westlake_survival.lib import search, new_books, Book, Loan

    books = search("机器学习", kind="title")
    for b in books:
        print(b.title, b.call_no, b.location)

个人借阅需先完成 SSO 登录（:mod:`westlake_survival.sso`）::

    from westlake_survival.lib import my_loans
    for loan in my_loans():
        print(loan.title, loan.due_date)
"""

from __future__ import annotations

from westlake_survival.lib.models import Book, Loan
from westlake_survival.lib.opac import (
    book_detail,
    my_loans,
    new_books,
    search,
    search_catalog,
)

__all__ = [
    "Book",
    "Loan",
    "search",
    "search_catalog",
    "book_detail",
    "new_books",
    "my_loans",
]