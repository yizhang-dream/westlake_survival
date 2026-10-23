"""把 capture_map.py 的原始抓取结果规整成随包发布的地图数据集。

原始结构只保证「端点 → 记录数组」，字段名因接口而异；本脚本做三件事：

1. 丢弃与地图无关的端点（配置、字典、用户信息等）；
2. 去重（同一端点内按 JSON 序列化后的内容去重）；
3. 写 ``src/westlake_survival/data/campus_map.json``，带生成时间与来源。

用法::

    python tools/build_map_dataset.py raw_map_capture.json \
        --out src/westlake_survival/data/campus_map.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

#: 明确与地图无关的端点片段（命中即跳过）。
SKIP_PARTS = ("ndConfig", "dict/", "user/info", "auth/", "log/", "menu/")

#: 名称字段：至少要有一个非空字符串，否则这条记录无法被检索。
NAME_FIELDS = ("name", "title", "poiName", "buildingName", "areaName", "facilityName", "text")


def is_useful(record: dict) -> bool:
    """记录是否可检索（有名称字段且不是纯配置项）。"""
    if not isinstance(record, dict):
        return False
    return any(isinstance(record.get(key), str) and record.get(key).strip() for key in NAME_FIELDS)


def build(source_path: Path, out_path: Path) -> int:
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    endpoints = raw.get("endpoints") or {}
    cleaned: dict[str, list] = {}
    dropped: list[str] = []

    for endpoint, rows in endpoints.items():
        if any(part in endpoint for part in SKIP_PARTS):
            dropped.append(endpoint)
            continue
        if not isinstance(rows, list):
            continue
        seen = set()
        kept = []
        for row in rows:
            if not is_useful(row):
                continue
            signature = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            kept.append(row)
        if kept:
            cleaned[endpoint] = kept
        else:
            dropped.append(endpoint)

    if not cleaned:
        print("没有可用的地图记录，未生成数据集。", file=sys.stderr)
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": raw.get("source") or "https://map.westlake.edu.cn",
                "captured_at": raw.get("captured_at") or "",
                "endpoints": cleaned,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    total = sum(len(rows) for rows in cleaned.values())
    print(f"数据集已生成：{len(cleaned)} 个端点、{total} 条记录 → {out_path}")
    for endpoint, rows in cleaned.items():
        print(f"  {endpoint}: {len(rows)} 条")
    if dropped:
        print(f"已跳过 {len(dropped)} 个端点：{', '.join(sorted(set(dropped))[:5])}…")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="规整地图抓取结果成数据集")
    parser.add_argument("source", help="capture_map.py 输出的 JSON")
    parser.add_argument(
        "--out",
        default="src/westlake_survival/data/campus_map.json",
        help="数据集输出路径（默认随包位置）",
    )
    args = parser.parse_args()
    return build(Path(args.source), Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
