# 环境自检：`westlake doctor`

在调用本工具前，应首先确认当前运行环境的完整性。`westlake doctor` 提供了前置检查入口，避免在命令执行过程中因缺少依赖、解释器路径错位或账号未配置而突发异常。

## 契约

`westlake doctor`（等效 `python -m westlake_survival doctor`）逐项检查并输出对应的修复建议：

| 检查 | ok | 缺失/异常时 |
| --- | --- | --- |
| 解释器 | Python ≥ 3.10 | `missing`：装 Python 3.10+ 后重装包 |
| 包本体 | 可导入 + 版本 + 路径 | 跑不起来时本命令根本不会执行 |
| 命令 `westlake` | 在 PATH 上且与当前解释器同一环境 | `warn`：不在 PATH（用 `python -m`）/ 不是同一环境（两个环境各装一份） |
| Web 界面（基础依赖） | flask 已装 | `missing`：`pip install -e .`（缺它通常是旧包或 `--no-deps` 装的） |
| 钥匙串 `[secure]` | keyring 已装且取到真实后端（detail 带后端名） | `missing`：`pip install -e '.[secure]'`（降级为明文文件）；`warn`：已装但无可用后端（无桌面/D-Bus 的 Linux 常见，凭据退明文文件，可接受） |
| 分享 `share` | playwright 已装 | `warn`（可选增强，2026-10-29）：缺它 share 讲义 / hosts 渲染深挖 / CARSI 校外 SSO 三条链路自动降级，其余功能不受影响、不影响退出码 |
| 校园账号 | 有凭据（只报来源） | `warn`：提示用户在网页「设置」页自行填写，Agent 不代填 |
| Canvas 令牌 | 有或走统一密码 | 信息项，不影响可用性 |
| HPC AI 令牌 | 仅报告是否已配置，不显示首尾字符 | 信息项；未配置时提示 `westlake hpc sync-key`，体检不会同步或验证令牌 |
| 网络（直连） | 公开站点可直连 | `warn`：提示先确认能上网；校外访问教务/Canvas 需 VPN |
| 版本契约与更新 | 当前版本与更新提示 | 新版可用时报 `warn`；`--offline` 跳过在线更新检查 |

- `--json` 输出 `{"ok", "missing": [...], "warn": [...], "checks": [...]}`，便于 Agent 判断；
- `--offline` 跳过联网探测；
- 退出码：有任何 `missing` 为 1，否则 0；
- **绝不回显**学号、密码、令牌，只报有无与路径；文本与 JSON 输出均不包含令牌的首尾片段。

## 为什么「解释器一致」要单独检查

最常见的运行异常并非未安装工具包，而是多 Python 环境导致的路径错位：`westlake` 命令位于环境 A 的 `Scripts/` 目录，而调用脚本使用的是环境 B 的 Python 解释器，导致无法正常导入模块或产生凭据隔离问题。doctor 通过比对命令路径与 `sys.executable` 路径，若存在分歧则提示改用 `python -m westlake_survival` 保证环境一致。

## 端到端核验

| 链路 | 输入 | 核对内容 |
| --- | --- | --- |
| 正常环境 | `westlake doctor` | 每项状态与实际配置相符；无 `missing` 时退出码 0 |
| JSON | `westlake doctor --json --offline` | 可解析为上述 JSON 结构；不执行网络和在线更新检查 |
| 未装可选依赖 | 干净 venv 安装基础包后运行 `python -m westlake_survival doctor --offline` | 缺 keyring 报 `missing` 并给出修复命令；缺 playwright 报 `warn`，两者不混同 |
| 令牌保密 | 隔离 `WESTLAKE_HOME`、禁用钥匙串，分别通过环境变量和本地文件提供虚构 HPC 令牌，再运行文本与 JSON 体检 | 仅报告“已配置”，两种输出均不含虚构令牌或其首尾片段；未配置时给出配置指引 |

## 不做的事

- **不自动安装依赖**：doctor 仅定位问题并输出建议命令，不修改运行环境，避免未经确认的静默安装。
- **不代填用户凭据**：账号信息由用户在本地网页「设置」页录入。
