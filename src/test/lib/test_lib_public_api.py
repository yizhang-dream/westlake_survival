"""公开 API 导入与模型行为的冒烟测试。"""

from __future__ import annotations

import westlake_survival.lib as lib
from westlake_survival.lib import Book, Loan


def test_public_names_importable() -> None:
    # 与验收标准一致：from westlake_survival.lib import
    # search, new_books, my_loans, Book, Loan
    names = ("search", "search_catalog", "book_detail", "new_books", "my_loans", "Book", "Loan")
    for name in names:
        assert name in lib.__all__
        assert hasattr(lib, name)


def test_book_defaults_tolerate_missing_fields() -> None:
    book = Book(title="仅题名")
    assert book.author == ""
    assert book.call_no == ""
    assert book.to_dict()["title"] == "仅题名"


def test_loan_renewable_optional() -> None:
    loan = Loan(title="书")
    assert loan.renewable is None
    assert loan.to_dict()["barcode"] == ""