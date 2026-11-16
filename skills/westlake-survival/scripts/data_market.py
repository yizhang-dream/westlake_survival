"""Read the portal data market with the locally configured account.

CLI output contains counts, field names and catalog metadata. Use MarketClient
in-process to select personal business fields without printing entire records.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from westlake_survival.market import (
        ALLOWED_REQUESTS,
        BASE,
        CURRENT_ACCOUNT,
        FILTERS,
        KINDS,
        MarketClient,
        MarketError,
        PREFIX,
        USER_INFO,
        summarize,
    )
except ImportError:  # 未安装包时的兼容回退：直接挂载仓库 src/
    _SRC = Path(__file__).resolve().parents[3] / "src"
    if _SRC.is_dir() and str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    from westlake_survival.market import (
        ALLOWED_REQUESTS,
        BASE,
        CURRENT_ACCOUNT,
        FILTERS,
        KINDS,
        MarketClient,
        MarketError,
        PREFIX,
        USER_INFO,
        summarize,
    )

__all__ = [
    "ALLOWED_REQUESTS",
    "BASE",
    "CURRENT_ACCOUNT",
    "FILTERS",
    "KINDS",
    "MarketClient",
    "MarketError",
    "PREFIX",
    "USER_INFO",
    "main",
    "summarize",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", choices=KINDS)
    parser.add_argument("--summary", action="store_true", help="目录也仅输出数量和字段名")
    parser.add_argument("--page-size", type=int, default=100, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    try:
        with MarketClient() as client:
            data = client.fetch(args.query, page_size=args.page_size)
        print(json.dumps(summarize(args.query, data, counts_only=args.summary), ensure_ascii=False, indent=2))
    except MarketError as exc:
        parser.exit(1, str(exc) + "\n")
    except Exception:
        parser.exit(1, "数据市集查询失败；先运行 westlake doctor 检查本机环境与账号配置。\n")


if __name__ == "__main__":
    main()
