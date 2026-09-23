"""每日快照（context）示例。

用途
    打印「此刻西湖」快照：日期 / 周次 / 学期、最近校历事件、下班车、
    天气 / AQI（联网时）、最近作业截止（配置了 Canvas 令牌时）。

前置条件
    - 无。``Level.TERSE`` 纯本地计算，离线也能跑；
      ``Level.NORMAL`` / ``Level.VERBOSE`` 的联网项失败会自动降级为空。

运行::

    python examples/quickstart_context.py
    python examples/quickstart_context.py verbose   # 也可取 terse / normal
"""

from __future__ import annotations

import sys

from westlake_survival.context import Level, snapshot

#: 命令行档位名 -> :class:`Level`。
_LEVELS = {level.value: level for level in Level}


def main() -> int:
    name = sys.argv[1].lower() if len(sys.argv) > 1 else "normal"
    level = _LEVELS.get(name)
    if level is None:
        print(f"未知档位 {name!r}，可选：{', '.join(_LEVELS)}", file=sys.stderr)
        return 2

    try:
        context = snapshot(level)
    except Exception as exc:  # 兜底：不让示例以堆栈收场
        print(f"生成快照失败：{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1

    print(context.to_str())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
