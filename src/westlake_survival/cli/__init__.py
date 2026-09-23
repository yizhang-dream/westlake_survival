"""``westlake_survival.cli`` —— 统一命令行入口（``westlake <子命令>``）。

顶层 click group 定义在 :mod:`westlake_survival.cli.main`，本模块负责：

1. Windows 控制台兜底——中文 Windows 默认代码页为 GBK，无法编码输出里的
   部分字符时会抛 :class:`UnicodeEncodeError`；这里在导入时尝试把
   ``stdout`` / ``stderr`` 重配置为 UTF-8，失败静默（管道/已关闭流等场景）。
2. 把 :data:`cli` 重新导出，供 ``pyproject.toml`` 的
   ``[project.scripts] westlake = "westlake_survival.cli:cli"`` 使用。
"""

from __future__ import annotations

import sys


def _configure_windows_streams() -> None:
    """Windows 下把标准输出/错误流重配置为 UTF-8（失败静默）。"""
    if sys.platform != "win32":  # pragma: no cover - 非 Windows 平台
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 - 流已关闭/被替换等，忽略
            pass


# 先配置输出流，再导入命令实现，确保任何打印都走 UTF-8 流。
_configure_windows_streams()

from westlake_survival.cli.main import cli  # noqa: E402  (须在流配置之后)

__all__ = ["cli"]
