"""图书馆模块的数据模型：书目与借阅记录。

字段全部带默认空值，容忍老 OPAC 页面缺字段（不同书目类型返回的
著录项并不一致）。模型只做数据承载，解析逻辑在 :mod:`opac`。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Book:
    """一条书目记录（检索结果或详情页）。

    Attributes:
        title: 题名。
        author: 责任者（作者）。
        publisher: 出版社。
        publish_year: 出版年。
        call_no: 索书号。
        isbn: ISBN/ISSN。
        location: 馆藏地/分馆（如"云谷校区""云栖校区"）。
        holding_status: 在馆状态（"在馆""借出"等），检索列表可能为空，
            由 :func:`westlake_survival.lib.opac.book_detail` 补全。
        detail_url: 书目详情页绝对 URL。
    """

    title: str = ""
    author: str = ""
    publisher: str = ""
    publish_year: str = ""
    call_no: str = ""
    isbn: str = ""
    location: str = ""
    holding_status: str = ""
    detail_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """返回字段字典（便于 JSON 序列化/CLI 输出）。"""
        return asdict(self)


@dataclass
class Loan:
    """一条当前借阅记录（读者页解析结果）。

    Attributes:
        title: 题名。
        barcode: 条码号（馆藏条码，续借/归还时用）。
        due_date: 应还日期（原样字符串，通常 ``YYYY-MM-DD``）。
        renewable: 是否可续借（解析不确定时为 ``None``）。
        location: 馆藏地/分馆。
    """

    title: str = ""
    barcode: str = ""
    due_date: str = ""
    renewable: bool | None = None
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["Book", "Loan"]