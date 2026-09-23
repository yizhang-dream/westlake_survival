"""``python -m westlake_survival`` 入口：等价于 ``westlake`` 命令。"""

from __future__ import annotations

from westlake_survival.cli import cli

if __name__ == "__main__":
    cli()
