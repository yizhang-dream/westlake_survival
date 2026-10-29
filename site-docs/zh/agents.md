# Agent 集成

westlake_survival 面向自动化流程与 AI Agent 提供了结构化接口与安全约束，支持以下接入方式：

## 1. 基于 `AGENTS.md` 规范的 Agent（ZCode、DSH、Codex、Claude Code、Cursor 等）

根目录 [AGENTS.md](https://github.com/yizhang-dream/westlake_survival/blob/main/AGENTS.md) 约定了行为规范、调用入口与验证流程；完成账号配置后直接调用 `westlake` CLI。

## 2. Python 库（进程内 API）

```python
import westlake_survival
from westlake_survival.sis import get_schedule
for s in get_schedule():
    print(s.weekday, s.start_time, s.title)
```

[examples/](https://github.com/yizhang-dream/westlake_survival/tree/main/examples) 提供了常用调用示例；安装 `westlake-survival` 后可直接在代码中引用。

## 3. Skill 扩展接入

技能定义文件位于 [skills/westlake-survival/SKILL.md](https://github.com/yizhang-dream/westlake_survival/blob/main/skills/westlake-survival/SKILL.md)，将其复制至对应 Agent 框架的技能目录即可加载：

```bash
cp -r westlake_survival/skills/westlake-survival ~/.zcode/skills/   # ZCode；其他代理用 ~/.agents/skills/、~/.claude/skills/
```

此外提供 `westlake-mcp` 服务端，便于仅支持 Tool Call 的客户端（如 Claude Desktop）以 MCP 协议接入。

## 写操作安全拦截（consequence）

写操作受限在五项行为内：`canvas submit / reply / send` 以及 `booking book / cancel`。所有写操作统一经过 [consequence.py](https://github.com/yizhang-dream/westlake_survival/blob/main/src/westlake_survival/consequence.py) 拦截与校验：

- 未附加 `--yes`：打印结构化风险描述（操作目标 / 风险 / 严重度 / 可逆性）并以退出码 1 终止；
- `--dry-run`（submit / book）：只预检不执行；
- 采用非交互式机制，避免子进程在管道 stdin 场景下阻塞。

## 环境接入验证

```bash
westlake doctor --json    # 确认各项检查无异常后再开展后续任务
```

账号信息由用户在本地网页「设置」页录入，Agent 严禁代填或索取密码。
