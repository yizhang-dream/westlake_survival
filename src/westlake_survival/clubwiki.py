"""社团简介的离线补充数据（改写自 WikiLake）。

WikiLake（https://wiki.mestlake.cc/clubs/ ）是西湖大学学生自建的校园百科，
非官方站点、未声明许可证。这里只保留**改写后的一句话事实介绍**，逐条附原文
链接，不含负责人姓名、联系方式与照片；版权归 WikiLake 贡献者，见
:data:`clubwiki.clubs` 返回值里的 ``meta``。

数据随包内置（``data/wikilake_clubs.json``，2026-10-27 抓取），运行时不联网，
因此 /sis 社团目录的简介在无凭据、无校园网时同样可读。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

__all__ = ["DATA_PATH", "catalog", "clubs", "lookup", "annotate"]

#: 内置数据文件（跟随包分发）。
DATA_PATH = Path(__file__).with_name("data") / "wikilake_clubs.json"

#: 归一化时丢弃的修饰词与分类后缀。
_DROP_PREFIXES = ("西湖大学",)
_DROP_SUFFIXES = ("社团", "协会", "俱乐部", "社", "club")
_DROP_CHARS = re.compile(r"[\s·・_\-—－（）()\[\]【】「」\"'《》,，.。]")


@lru_cache(maxsize=1)
def catalog() -> dict:
    """读取内置社团简介，返回 ``{"meta": {...}, "clubs": [{name, summary, url}]}``。

    Raises:
        RuntimeError: 数据文件缺失或格式不对（属打包问题，不在运行时降级）。
    """
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - 打包错误
        raise RuntimeError(f"WikiLake 社团数据不可用：{exc}") from exc
    return {"meta": dict(raw.get("meta") or {}), "clubs": list(raw.get("clubs") or [])}


def clubs() -> list[dict]:
    """内置社团简介列表（每条含 ``name`` / ``summary`` / ``url``）。"""
    return catalog()["clubs"]


def _norm(name: str) -> str:
    """归一化名称：去空白标点、去「西湖大学」前缀与社团类后缀。"""
    text = _DROP_CHARS.sub("", str(name or ""))
    text = re.sub(r"[×✕╳]", "x", text).lower()
    for prefix in _DROP_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in _DROP_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
            break
    return text


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    """归一化名称 → 简介条目（同名取先出现者）。"""
    table: dict[str, dict] = {}
    for item in clubs():
        key = _norm(item.get("name", ""))
        if key:
            table.setdefault(key, item)
    return table


def lookup(name: str) -> dict | None:
    """按社团名查简介；先精确匹配归一化名，再在长度 ≥3 时做包含匹配。"""
    key = _norm(name)
    if not key:
        return None
    table = _index()
    if key in table:
        return table[key]
    if len(key) >= 3:
        hits = [(norm, item) for norm, item in table.items() if key in norm or norm in key]
        if hits:
            return max(hits, key=lambda pair: len(pair[0]))[1]
    return None


def annotate(items: list) -> list[dict]:
    """给社团行补 ``wiki_summary`` / ``wiki_url``（命中时），未命中原样返回。

    Args:
        items: :class:`~westlake_survival.sis.aid.OrgRecord` 列表或等价的字典列表。

    Returns:
        与 *items* 同序的新列表；每项为字典，命中者多两个键。
    """
    out: list[dict] = []
    for item in items:
        row = item if isinstance(item, dict) else item.to_dict()
        hit = lookup(row.get("name") or row.get("club_name") or "")
        if hit:
            row = {**row, "wiki_summary": hit["summary"], "wiki_url": hit["url"]}
        out.append(row)
    return out
