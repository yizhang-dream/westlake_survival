# Agent 集成

本仓库为 AI 代理而设计。三种接法按需选、可叠加：

## 1. 读 `AGENTS.md` 的代理（ZCode、DSH、Codex、Claude Code、Cursor……）

clone 即用——根目录 [AGENTS.md](https://github.com/yizhang-dream/westlake_survival/blob/main/AGENTS.md) 写明纪律、入口与验证方式，会话自动读到；配好账号后直接差遣 `westlake` CLI。

## 2. Python 库（进程内 API，会跑代码的代理最短路径）

```python
import westlake_survival
from westlake_survival.sis import get_schedule
for s in get_schedule():
    print(s.weekday, s.start_time, s.title)
```

[examples/](https://github.com/yizhang-dream/westlake_survival/tree/main/examples) 有可直接跑的样例；`pip install westlake-survival` 后无需仓库。

## 3. 技能（Skill）机制

技能文档在 [skills/westlake-survival/SKILL.md](https://github.com/yizhang-dream/westlake_survival/blob/main/skills/westlake-survival/SKILL.md)，拷进你的代理技能根即可被发现：

```bash
cp -r westlake_survival/skills/westlake-survival ~/.zcode/skills/   # ZCode；其他代理用 ~/.agents/skills/、~/.claude/skills/
```

MCP 服务器 `westlake-mcp` 作为兼容层保留，面向只能调用工具的客户端（Claude Desktop 等）；有终端的代理用上面三条即可。

## 写操作安全（consequence 确认门）

写操作仅五条：`canvas submit / reply / send`、`booking book / cancel`。统一走 [consequence.py](https://github.com/yizhang-dream/westlake_survival/blob/main/src/westlake_survival/consequence.py)：

- 未 `--yes`：打印结构化风险描述（改什么 / 风险 / 严重度 / 可逆性）并以退出码 1 结束；
- `--dry-run`（submit / book）：只预检不执行；
- 刻意不做交互 y/n——Agent 管道 stdin 下会挂死。

## 接手第一步

```bash
westlake doctor --json    # 全绿再干活
```

账号不由代理填：请使用者在网页「设置」页本人填写。
