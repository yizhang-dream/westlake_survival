# Agent 使用须知（westlake_survival）

任何在本仓库工作的 AI 编码代理（ZCode、DSH、Codex、Claude Code、Cursor……）请先读本文，再动手。

## 工具入口

- 项目是什么、怎么装、能做什么：[README](README.md)
- 命令路由与行为规则（操作本工具的主文档）：[.zcode/skills/westlake-survival/SKILL.md](.zcode/skills/westlake-survival/SKILL.md)
- 完整命令示例 / Python API 方法表 / MCP 注册：[docs/skill_reference.md](docs/skill_reference.md)
- CLI / MCP / WebUI 能力变更时，同步更新 SKILL.md 与 README 能力表

## 纪律（硬约束）

- 仅访问使用者本人有权的数据：不绕过权限、不代抢课、不擅自写学校系统。live 查询与写操作须在任务授权和凭据范围内；离线 fixture、缓存与真实服务结果分别说明。
- 凭据与会话不打印、不记录、不提交，只报来源有无。凭据只存本机、不跨机器同步（[docs/credential_single_store.md](docs/credential_single_store.md)）；Windows 明文文件不能仅凭 0600 宣称安全。
- 个人数据（成绩、学籍、住宿、资助等）输出给第三方前默认脱敏。
- 保留许可与第三方署名：社团简介改写自学生自建百科 WikiLake（[docs/clubwiki.md](docs/clubwiki.md)），项目结构参考 [sustech_survival](https://github.com/dumixthestpd/sustech_survival)。

## 接手与验证

- 接手第一步跑 `westlake doctor` 体检环境（解释器/依赖/命令一致性/账号/网络，缺什么给一条能直接抄的修复命令，见 [docs/doctor.md](docs/doctor.md)）。
- 功能验证走端到端真跑：`python tools/module_smoke.py`（只读 CLI 逐条体检）、`python tools/webui_smoke.py`（进程内起真实服务逐页断言 200）；本仓库不维护单元测试，不新增单测文件。
- 提交前跑 `python tools/pii_scan.py`，确认无真实学号等个人信息。
