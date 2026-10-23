"""地图数据集（一次性抓取、长期离线复用）。

设计动机
========
``map.westlake.edu.cn`` 的每个数据接口都要令牌（实测匿名一律
``10031 缺少请求授权令牌``），但**地图数据本身是全校公共的**：楼名、区域、
设施位置，与谁登录无关。所以正确做法不是让每个用户都配一次账号，而是
**用任意一个有效账号成功抓一次，把结果固化成数据集随包发布**，之后所有人
离线可查。账号只在「抓取那一次」需要。

数据集文件
==========
``src/westlake_survival/data/campus_map.json``，结构刻意保持宽松（抓取时
端点与字段名未知，先原样存，后续按需规整）::

    {
      "generated_at": "2026-10-23T17:00:00",
      "source": "https://map.westlake.edu.cn",
      "endpoints": {
        "/api/nsc/...": [ {...原始记录...}, ... ],
        ...
      }
    }

查询时把各端点记录摊平，按「名称字段」匹配：``name`` / ``title`` /
``poiName`` / ``buildingName`` / ``areaName`` / ``facilityName`` 里第一个
非空且为字符串的字段。

抓取与生成见仓库 ``tools/capture_map.py`` 与 ``tools/build_map_dataset.py``。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from westlake_survival.exceptions import ParseError

__all__ = [
    "DATASET_PATH",
    "NAME_FIELDS",
    "PoiHit",
    "MapDataset",
    "dataset_available",
    "dataset_path",
    "load_dataset",
]

logger = logging.getLogger(__name__)

#: 随包发布的数据集文件。
DATASET_PATH = Path(__file__).with_name("data") / "campus_map.json"

#: 记录里可能承载名称的字段（按优先级）。
NAME_FIELDS = ("name", "title", "poiName", "buildingName", "areaName", "facilityName", "text")


@dataclass
class PoiHit:
    """一条地图记录。

    :attr:`endpoint` 说明它来自哪个接口，:attr:`fields` 保留原始字段供调用方
    自行取用（不同接口字段不同，强类型化会丢信息）。
    """

    name: str
    endpoint: str
    fields: dict = field(default_factory=dict)

    def brief(self) -> str:
        """一行摘要：优先拼接常见的区域/楼层字段。"""
        parts = [self.name]
        for key in ("areaName", "buildingName", "floorName", "floor", "categoryName", "typeName"):
            value = self.fields.get(key)
            if isinstance(value, str) and value.strip() and value != self.name:
                parts.append(value.strip())
        return " · ".join(parts)


@dataclass
class MapDataset:
    """已加载的地图数据集。"""

    generated_at: str = ""
    source: str = ""
    endpoints: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return sum(len(rows) for rows in self.endpoints.values() if isinstance(rows, list))

    def matches(self, endpoint_part: str) -> list[str]:
        """按端点子串筛选端点名。"""
        return [key for key in self.endpoints if endpoint_part in key]

    def records(self, endpoint_part: str | None = None) -> list[PoiHit]:
        """摊平各端点记录；``endpoint_part`` 给定时只取匹配端点。"""
        hits: list[PoiHit] = []
        for endpoint, rows in self.endpoints.items():
            if endpoint_part and endpoint_part not in endpoint:
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = _name_of(row)
                if name:
                    hits.append(PoiHit(name=name, endpoint=endpoint, fields=dict(row)))
        return hits

    def search(self, keyword: str, *, limit: int | None = None) -> list[PoiHit]:
        """按名称子串搜索（大小写不敏感）。"""
        needle = (keyword or "").strip().casefold()
        if not needle:
            return []
        found = [hit for hit in self.records() if needle in hit.name.casefold()]
        if limit is not None:
            found = found[: max(0, limit)]
        return found


def _name_of(record: dict) -> str:
    """取记录的名称字段（按 :data:`NAME_FIELDS` 优先级）。"""
    for key in NAME_FIELDS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def dataset_path() -> Path:
    """数据集实际路径：环境变量 ``WESTLAKE_MAP_DATASET`` 可覆盖随包默认位置。"""
    override = os.environ.get("WESTLAKE_MAP_DATASET", "").strip()
    return Path(override) if override else DATASET_PATH


def dataset_available() -> bool:
    """数据集文件是否存在。"""
    return dataset_path().exists()


def load_dataset(path: Path | None = None) -> MapDataset:
    """读取数据集。

    Raises:
        FileNotFoundError: 数据集尚未生成（调用方应给出抓取指引）。
        ParseError: 文件不是约定 JSON 结构。
    """
    target = path or dataset_path()
    if not target.exists():
        raise FileNotFoundError(str(target))
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ParseError(f"地图数据集读取失败：{target}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("endpoints"), dict):
        raise ParseError(f"地图数据集结构异常（缺 endpoints）：{target}")
    return MapDataset(
        generated_at=str(raw.get("generated_at") or ""),
        source=str(raw.get("source") or ""),
        endpoints=raw["endpoints"],
    )
