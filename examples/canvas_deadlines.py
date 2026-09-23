"""列出 Canvas 最近到期的作业。

用途
    汇总所有 active 课程中即将到期的作业，按截止时间升序打印。

前置条件
    - Canvas API token（在 Canvas 网页「账户 → 设置 → 新建访问令牌」自助生成）。
      任选一种提供：环境变量 ``WESTLAKE_CANVAS_TOKEN``，或写入
      ``~/.westlake_survival/canvas_token.txt``（首行即令牌）。

运行::

    export WESTLAKE_CANVAS_TOKEN="<你的令牌>"
    python examples/canvas_deadlines.py        # 默认 10 条
    python examples/canvas_deadlines.py 20     # 最多 20 条
"""

from __future__ import annotations

import sys

from westlake_survival.canvas import canvas


def main() -> int:
    limit = 10
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            print(f"条数应为整数，得到 {sys.argv[1]!r}", file=sys.stderr)
            return 2

    try:
        deadlines = canvas().upcoming_deadlines(limit=limit)
    except Exception as exc:  # 兜底：把认证/网络问题说清楚
        print(f"获取作业截止失败：{exc.__class__.__name__}: {exc}", file=sys.stderr)
        print(
            "提示：请确认已设置 WESTLAKE_CANVAS_TOKEN，"
            "或已写入 ~/.westlake_survival/canvas_token.txt。",
            file=sys.stderr,
        )
        return 1

    if not deadlines:
        print("最近没有即将到期的作业。")
        return 0

    for assignment in deadlines:
        due = assignment.due_at.strftime("%Y-%m-%d %H:%M") if assignment.due_at else "无截止时间"
        print(f"[{due}] {assignment.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
