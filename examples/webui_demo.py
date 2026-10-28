"""启动本地 Web UI 示例。

用途
    在本地起一个 Flask 服务，用浏览器查看课表 / 班车 / Canvas 截止 / 每日快照。

前置条件
    - 已装本包：``pip install -e .``（Flask 是基础依赖，无需 ``[webui]`` extra）。
    - 数据源凭据按需配置（Canvas / SIS 相关页面需要）。

运行::

    python examples/webui_demo.py           # 默认 127.0.0.1:2018
    python examples/webui_demo.py 8080      # 自定义端口

启动后用浏览器打开 http://127.0.0.1:2018/ 。按 Ctrl+C 退出。
"""

from __future__ import annotations

import sys

from westlake_survival.webui import run


def main() -> int:
    port = 2018
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"端口应为整数，得到 {sys.argv[1]!r}", file=sys.stderr)
            return 2

    print(f"启动 Web UI：http://127.0.0.1:{port}/ （Ctrl+C 退出）")
    try:
        run(port=port)
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    except Exception as exc:  # 兜底：依赖缺失 / 端口占用
        print(f"启动 Web UI 失败：{exc.__class__.__name__}: {exc}", file=sys.stderr)
        print('提示：请先装本包——pip install -e .（Flask 已随基础依赖安装）', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
