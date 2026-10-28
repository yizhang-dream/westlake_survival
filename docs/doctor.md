# 环境自检：`westlake doctor`

Agent 拿到本 skill 的第一件事，是判断「这台机器上的环境对不对」。2026-10-28 之前没有这个入口：缺 flask、缺 playwright、`westlake` 指向另一个解释器、账号没配——每种情况都只在具体命令报错时才暴露，Agent 只能回去读 README 猜。

## 契约

`westlake doctor`（等效 `python -m westlake_survival doctor`）逐项检查并给出修复命令：

| 检查 | ok | 缺失/异常时 |
| --- | --- | --- |
| 解释器 | Python ≥ 3.10 | `missing`：装 Python 3.10+ 后重装包 |
| 包本体 | 可导入 + 版本 + 路径 | 跑不起来时本命令根本不会执行 |
| 命令 `westlake` | 在 PATH 上且与当前解释器同一环境 | `warn`：不在 PATH（用 `python -m`）/ 不是同一环境（两个环境各装一份） |
| Web 界面（基础依赖） | flask 已装 | `missing`：`pip install -e .`（缺它通常是旧包或 `--no-deps` 装的） |
| 钥匙串 `[secure]` | keyring 已装 | `missing`：`pip install -e '.[secure]'`（降级为明文文件） |
| 分享 `share` | playwright 已装 | `missing`：`pip install playwright && playwright install chromium` |
| 校园账号 | 有凭据（只报来源） | `warn`：让**本人**在网页「设置」页填一次，Agent 不代填 |
| Canvas 令牌 | 有或走统一密码 | 信息项，不影响可用性 |
| 网络（直连） | 公开站点可直连 | `warn`：提示先确认能上网；校外访问教务/Canvas 需 VPN |

- `--json` 输出 `{"ok", "missing": [...], "warn": [...], "checks": [...]}`，便于 Agent 判断；
- `--offline` 跳过联网探测；
- 退出码：有任何 `missing` 为 1，否则 0；
- **绝不回显**学号、密码、令牌，只报有无与路径。

## 为什么「解释器一致」要单独检查

最常见的「装了却用不了」不是没装，而是**两个环境各装一份**：`westlake` 命令在 A 环境的 `Scripts/`，Agent 用 B 环境的 `python` 写脚本，于是 `import westlake_survival` 失败、或者读到的凭据不是同一份（凭据只存一份、按环境隔离）。doctor 用「命令所在目录 vs `sys.executable` 所在目录」比对，不一致就提示改用 `python -m westlake_survival` 对齐。

## 验收（端到端，2026-10-28）

| 链路 | 输入 | 结果 |
| --- | --- | --- |
| 正常环境 | 本机 venv 直接 `westlake doctor` | 9 项全 ✔，退出码 0 |
| JSON | `westlake doctor --json --offline` | `{"ok": true, "missing": [], "warn": []}` |
| 缺可选依赖 | 新建干净 venv 只 `pip install -e .`（不装 extras），再 `python -m westlake_survival doctor --offline` | 报 2 项 `missing`（keyring / playwright）各带修复命令——flask 自 2026-10-28 起在基础依赖里，不再报缺；`westlake` 报「与当前解释器不是同一个环境」；校园账号报未配置；退出码 1 |

## 不做的事

- **不自动装包**：修复命令由 Agent/人执行，doctor 只体检不改环境（避免在用户机器上静默安装）。
- **不代填凭据**：账号只能由本人通过网页「设置」页写入。
