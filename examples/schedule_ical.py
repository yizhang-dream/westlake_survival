"""把 SIS 教务课表导出为 iCalendar 文件。

用途
    抓取本学期课表节次，生成 ``schedule.ics`` 导入日历。

前置条件
    - 学号 + 密码：见 README「快速开始」的三种凭据配置方式。
    - **校园网 / VPN**：SIS 仅校内可达（VPN 入口 https://vpn.westlake.edu.cn/）。

产出
    当前工作目录下 ``schedule.ics``。

运行::

    python examples/schedule_ical.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from westlake_survival.ical import save_ics
from westlake_survival.sis import get_schedule


def main() -> int:
    destination = Path("schedule.ics")
    try:
        sessions = get_schedule()
        save_ics(sessions, destination)
    except Exception as exc:  # 兜底：凭据 / 校园网 / SIS 端点问题
        print(f"导出课表失败：{exc.__class__.__name__}: {exc}", file=sys.stderr)
        print(
            "提示：需要学号密码（见 README 快速开始），并在校园网 / VPN 内运行；"
            "SIS 端点结构变化时本模块可能需要校准。",
            file=sys.stderr,
        )
        return 1

    print(f"已写入 {destination.resolve()}，共 {len(sessions)} 个节次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
