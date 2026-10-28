#!/usr/bin/env bash
# 双击启动（macOS）：起网页界面并自动打开浏览器。
# 首次运行会自动安装依赖（只需一次），之后直接进网页。
# 首次启动落在「设置」页，在那里填一次自己的学号与统一身份认证密码。
set -u
cd "$(dirname "$0")" || exit 1

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "没有找到 python3。请先安装 Python 3.10 或更新版本：https://www.python.org/downloads/"
  read -r -p "按回车关闭…" _
  exit 1
fi

if ! "$PY" -c "import westlake_survival, flask" >/dev/null 2>&1; then
  echo "首次运行：正在安装依赖，大约 1-2 分钟，请不要关闭这个窗口……"
  if ! "$PY" -m pip install -e '.[webui]'; then
    echo
    echo "安装失败。可以把上面的报错发给维护者，或手动运行："
    echo "  $PY -m pip install -e '.[webui]'"
    read -r -p "按回车关闭…" _
    exit 1
  fi
fi

echo
echo "正在启动……浏览器会自动打开；关掉这个窗口就停止服务。"
"$PY" -m westlake_survival
