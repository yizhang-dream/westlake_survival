# 首次启动：网页第一，账号配置第一

设计取向（2026-10-28）：前端显示是启动的第一优先级——使用者不同、本机配置不同，
所以启动后第一件事就是让人在网页里填一次自己的账号。

## 入口契约

| 场景 | 行为 |
| --- | --- |
| 裸命令 `westlake` | 起 WebUI 并打开浏览器（等价 `westlake go`） |
| 本机还没有账号 | 落地页直接是 `/setup`（「设置」）；保存且**验证通过**后 3 秒自动进仪表盘，未验证已保存则留在设置页（2026-10-29） |
| 已经配过账号 | 落地页是仪表盘 `/` |
| 直接访问 `/` 且未配置 | 302 到 `/setup` |
| 只想看公开功能 | `/setup` 上的「先看看公开功能」→ `/?skip=1`（校历/班车/新闻/地图都不需要账号） |
| 双击启动 | `start.bat`（Windows）/ `start.command`（macOS）/ `start.sh`（Linux，桌面也可双击）：找 Python（三脚本都拦 <3.10）→ 缺依赖就 `pip install -e '.[webui]'`（遇 Homebrew/Debian 系 Python 的 externally-managed 限制时自动落到仓库内 `.venv` 安装，此后优先复用）→ 起服务 |
| 终端装完即用 | `pip install -e .` 之后直接 `westlake`：Flask 自 2026-10-28 起是**基础依赖**，装完就有前端，不再需要 `[webui]` extra |
| 重复启动 | 同一端口已有本网页在跑 → 不再起第二个服务，直接把浏览器指过去（`westlake go` 打印「已在运行」） |
| 脚本 / 自动化 | `westlake --help`，或设 `WESTLAKE_NO_WEBUI=1` 让裸命令只打印帮助 |
| 终端配置 | `westlake setup` 无参跑 = **打开浏览器设置页并等网页完成配置**（`--wait` 缺省 600s，轮询凭据落盘即收尾；`--wait 0` 打开即返回）；**终端默认不问密码**，`--terminal` 才走终端提示（SSH 兜底）；全旗标 `--sid/--password` 属自动化代跑不弹不问（默认在浏览器前端敲账号密码） |

保存后：页面当场给出每个服务的结果，并区分「已验证并保存 / 未验证已保存」，
再给一个「进首页 →」按钮。验证没通过也落盘，不必重填（凭据只存一份，见
[credential_single_store.md](credential_single_store.md)）。

## 实现位置

- `src/westlake_survival/cli/main.py`：`cli()` 裸命令 → `go_cmd`；`_webui_entry_url()`
  按「有没有凭据」决定落地页；`_webui_probe_url()` 用 `/setup` 做就绪探针（仪表盘
  要现拉数据，实测冷启动 18 秒，拿它当探针会让浏览器白等）；`_webui_already_running()`
  按页面品牌串认出已在跑的实例；缺 Flask 的报错给出 `pip install -e .` / `pip install flask`。
- `pyproject.toml`：Flask 进基础依赖（`[webui]` extra 保留只为旧命令照常工作）。
- `src/westlake_survival/webui/app.py`：`/` 未配置时 `redirect(url_for("setup_page"))`，
  `?skip=1` 放行。
- `templates/setup.html`：未配置时显示「第 1 步」引导 + 跳过链接；保存后给「进首页」按钮。
- `templates/base.html`：引导横幅在设置页自身不再重复出现。
- `start.bat` / `start.command` / `start.sh`：双击/终端入口。`.bat` 刻意只写 ASCII——cmd 按本地代码页
  逐行解析批处理，UTF-8 中文会把命令行拆坏（实测过一版直接报「不是内部或外部命令」）。
  `.command` / `.sh` 与 `.bat` 同一底线：拦 <3.10 的解释器；Homebrew/Debian 系 Python 带
  `EXTERNALLY-MANAGED` 标记（pip 拒绝全局安装）时先建仓库内 `.venv` 再装，后续
  优先复用 `.venv/bin/python`（macOS/Linux 跨平台补齐，2026-10-28）。

## 验收（端到端，2026-10-28）

| 链路 | 输入 | 结果 |
| --- | --- | --- |
| 首次启动 | `WESTLAKE_HOME=/tmp/wl-firstrun WESTLAKE_NO_KEYRING=1 westlake go --no-browser --port 2401` | 日志给出 `.../setup`；`GET /` → 302 → `/setup`；`/setup` 200 且含「第 1 步」与 `/?skip=1`；`/?skip=1` 200 |
| 裸命令启动 | 同上环境，直接 `westlake` | 服务起在 2018；`GET /` → 302 → `/setup` |
| 裸命令经 `python -m` | `python -m westlake_survival` | 同上，302 → `/setup` |
| 已配置机器 | `westlake go --no-browser --port 2402` | 日志给出 `.../`；`GET /` → 200（不跳转）；`/setup` 200 |
| 双击脚本 | `WESTLAKE_NO_WEBUI=1 cmd /c start.bat`（正常 Windows PATH） | 跳过安装、进入应用；PATH 里只有 msys Python 时给出「no pip」提示；PATH 无 Python 时给出安装指引 |
| 全站页面 | `python tools/webui_smoke.py` | `{"pages": 32, "failed": []}` |
| 装完即用（2026-10-28 复核） | `pip install -e .` → `python -c "importlib.metadata.requires(...)"` | 依赖表含 `flask>=3.0`（基础依赖），无需 `[webui]` |
| 首次启动复核 | `WESTLAKE_HOME=/tmp/wl-firstrun WESTLAKE_NO_KEYRING=1 westlake go --no-browser --port 2401` | 日志 `Web 界面：http://127.0.0.1:2401/setup`；`GET /` → 302 → `/setup`；`/setup` 200 含「第 1 步」；`/?skip=1` 200 |
| 重复启动 | 2018 上已有实例时再跑 `westlake go --no-browser --port 2018` | 0.7s 打印「已在运行：…/」并以 0 退出，不起第二个服务 |
| 已配置机器 | `GET http://127.0.0.1:2018/` / `/setup` | 200 / 200（首页冷启动约 18s，故探针改用 `/setup`） |

## 已知

`src/test/webui/test_webui_index.py` 假设本机已配置账号（未配置时 `/` 会 302）。
本仓库不维护单元测试，验收以 `tools/webui_smoke.py` 与上面的真实链路为准。
