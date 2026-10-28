# 首次启动：网页第一，账号配置第一

2026-10-28 用户裁定：把前端显示作为启动的第一优先级——用户不同、本机配置不同，
所以启动后第一件事就是让人在网页里填一次自己的账号。

## 入口契约

| 场景 | 行为 |
| --- | --- |
| 裸命令 `westlake` | 起 WebUI 并打开浏览器（等价 `westlake go`） |
| 本机还没有账号 | 落地页直接是 `/setup`（「设置」），提示「第 1 步：填一次你自己的账号」 |
| 已经配过账号 | 落地页是仪表盘 `/` |
| 直接访问 `/` 且未配置 | 302 到 `/setup` |
| 只想看公开功能 | `/setup` 上的「先看看公开功能」→ `/?skip=1`（校历/班车/新闻/地图都不需要账号） |
| 双击启动 | `start.bat`（Windows）/ `start.command`（macOS）：找 Python → 缺依赖就 `pip install -e '.[webui]'` → 起服务 |
| 脚本 / 自动化 | `westlake --help`，或设 `WESTLAKE_NO_WEBUI=1` 让裸命令只打印帮助 |

保存后：页面当场给出每个服务的结果，并区分「已验证并保存 / 未验证已保存」，
再给一个「进首页 →」按钮。验证没通过也落盘，不必重填（凭据只存一份，见
[credential_single_store.md](credential_single_store.md)）。

## 实现位置

- `src/westlake_survival/cli/main.py`：`cli()` 裸命令 → `go_cmd`；`_webui_entry_url()`
  按「有没有凭据」决定落地页；缺 Flask 的报错改成「在仓库目录 `pip install -e '.[webui]'`」
  （本包未发布到 PyPI，旧文案指向一个不存在的包）。
- `src/westlake_survival/webui/app.py`：`/` 未配置时 `redirect(url_for("setup_page"))`，
  `?skip=1` 放行。
- `templates/setup.html`：未配置时显示「第 1 步」引导 + 跳过链接；保存后给「进首页」按钮。
- `templates/base.html`：引导横幅在设置页自身不再重复出现。
- `start.bat` / `start.command`：双击入口。`.bat` 刻意只写 ASCII——cmd 按本地代码页
  逐行解析批处理，UTF-8 中文会把命令行拆坏（实测过一版直接报「不是内部或外部命令」）。

## 验收（端到端，2026-10-28）

| 链路 | 输入 | 结果 |
| --- | --- | --- |
| 首次启动 | `WESTLAKE_HOME=/tmp/wl-firstrun WESTLAKE_NO_KEYRING=1 westlake go --no-browser --port 2401` | 日志给出 `.../setup`；`GET /` → 302 → `/setup`；`/setup` 200 且含「第 1 步」与 `/?skip=1`；`/?skip=1` 200 |
| 裸命令启动 | 同上环境，直接 `westlake` | 服务起在 2018；`GET /` → 302 → `/setup` |
| 裸命令经 `python -m` | `python -m westlake_survival` | 同上，302 → `/setup` |
| 已配置机器 | `westlake go --no-browser --port 2402` | 日志给出 `.../`；`GET /` → 200（不跳转）；`/setup` 200 |
| 双击脚本 | `WESTLAKE_NO_WEBUI=1 cmd /c start.bat`（正常 Windows PATH） | 跳过安装、进入应用；PATH 里只有 msys Python 时给出「no pip」提示；PATH 无 Python 时给出安装指引 |
| 全站页面 | `python tools/webui_smoke.py` | `{"pages": 32, "failed": []}` |

## 已知

`src/test/webui/test_webui_index.py` 假设本机已配置账号（未配置时 `/` 会 302）。
按 2026-10-11 裁定不维护单测，验收以 `tools/webui_smoke.py` 与上面的真实链路为准。
