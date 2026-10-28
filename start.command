#!/usr/bin/env bash
# 双击启动（macOS）：起网页界面并自动打开浏览器。
# 首次运行会自动安装依赖（只需一次），之后直接进网页。
# 首次启动落在「设置」页，在那里填一次自己的学号与统一身份认证密码。
set -u
cd "$(dirname "$0")" || exit 1

# 曾经落到仓库内 .venv（Homebrew/系统 Python 拒绝全局安装时的去处）就优先用它。
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
  echo "没有找到 python3。请先安装 Python 3.10 或更新版本：https://www.python.org/downloads/"
  read -r -p "按回车关闭…" _
  exit 1
fi

# 与 Windows 侧 start.bat 同一底线：低于 3.10 的零散解释器只会刷一屏噪音。
if ! "$PY" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
  echo "需要 Python 3.10 或更新版本（当前：$("$PY" -V 2>&1)）。"
  echo "请从 https://www.python.org/downloads/ 安装后，再双击本文件。"
  read -r -p "按回车关闭…" _
  exit 1
fi

if ! "$PY" -c "import westlake_survival, flask" >/dev/null 2>&1; then
  # Homebrew/系统 Python 带 EXTERNALLY-MANAGED 标记时 pip 拒绝全局安装，
  # 先在仓库内建独立环境，装进 .venv（gitignore 已忽略）。
  if [ ! -x ".venv/bin/python" ] && "$PY" -c "import os, sys, sysconfig; sys.exit(0 if os.path.exists(os.path.join(sysconfig.get_path('stdlib'), 'EXTERNALLY-MANAGED')) else 1)" >/dev/null 2>&1; then
    echo "这个 Python 不允许往全局装包，先在仓库内建独立环境 .venv……"
    "$PY" -m venv .venv
    PY=".venv/bin/python"
  fi
  echo "首次运行：正在安装依赖，大约 1-2 分钟，请不要关闭这个窗口……"
  if ! "$PY" -m pip install -e '.[webui]'; then
    echo
    echo "安装失败。可以把上面的报错发给维护者，或手动运行："
    echo "  $PY -m pip install -e '.[webui]'"
    echo "若提示 externally-managed / 不允许全局安装，可改用独立环境："
    echo "  python3 -m venv .venv && .venv/bin/pip install -e '.[webui]'"
    read -r -p "按回车关闭…" _
    exit 1
  fi
fi

echo
echo "正在启动……浏览器会自动打开；关掉这个窗口就停止服务。"
"$PY" -m westlake_survival
