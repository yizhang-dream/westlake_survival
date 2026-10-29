**改了什么 / 为什么** *(what & why — English welcome)*

**怎么验证的**（端到端：什么真实链路、什么输入、核对了什么结果）

<!-- 例：python tools/module_smoke.py canvas booking；python tools/webui_smoke.py -->

**自查**

- [ ] `python tools/pii_scan.py` 通过（无真实学号 / 凭据）
- [ ] SKILL.md、README 功能表、docs/skill_reference.md 已同步（CLI/MCP/WebUI 能力变更时）
- [ ] 未新增单元测试（本仓库只走端到端验证）
- [ ] 写操作仍限五条（canvas submit/reply/send、booking book/cancel），确认门未被削弱
