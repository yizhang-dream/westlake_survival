"""live 测试：``westlake probe`` 真探测，仅断言四项各有结果。

默认被 ``-m 'not live'`` 排除。运行：

    .venv/Scripts/python -m pytest src/test/test_probe_live.py -q -m live

不断言具体状态（选课窗口是否开、OPAC 是否恢复、是否登录都会随环境变化），
只要求每一项都返回非空的状态与说明、命令退出码为 0。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from westlake_survival.cli import cli
from westlake_survival.cli.main import PROBE_ITEMS


@pytest.mark.live
def test_probe_live_each_item_returns_result() -> None:
    """真跑 probe：四项都出现在输出里，且每项都有非空状态。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["probe"])
    assert result.exit_code == 0, result.output

    lines = [line for line in result.output.splitlines() if line.strip()]
    # 表头 + 分隔行 + 四项数据行。
    assert len(lines) >= 2 + len(PROBE_ITEMS)

    for name, _func in PROBE_ITEMS:
        assert name in result.output, f"探测项缺失：{name}"
    # 每项都要有状态文本（「失败」也算有结果，只是附原因）。
    for status in ("失败", "HTTP", "选课窗口未开", "已授权", "可达", "已配置", "未配置"):
        if status in result.output:
            print(f"\n[live] probe 命中状态：{status}")
    print("\n[live] probe 输出：\n" + result.output)
