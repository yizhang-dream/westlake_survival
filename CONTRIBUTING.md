# 贡献指南

单人维护为主，外部 issue / PR 欢迎，有空即审。

## 先问再写

- **bug 与小修** → 先开 issue（模板会问子系统与 doctor 输出），再提 PR。
- **较大改动**（新模块、动写操作边界）→ 先开 issue 标 `proposal`，设计对齐再写码。
- **使用问题** → 直接开 issue，写清在哪一步卡住。

## 语言

- `README.md`（中文）是正文正本；`README_en.md` 为英文翻译，随中文版同步修改。
- issue / PR / commit message：中英皆可。
- 代码标识符与注释英文优先；中文域名等专有名词做一次性注释即可。

## 开发环境

Python 3.10+：

```bash
git clone https://github.com/yizhang-dream/westlake_survival.git
cd westlake_survival
pip install -e .                 # 基础即全功能（含 WebUI 与钥匙串加密存储）
pip install -e '.[browser]'      # 可选增强：share 讲义 / hosts 渲染深挖 / CARSI 校外 SSO
```

## 验证纪律（重要）

本仓库**不维护单元测试**——功能与修复一律端到端验证（真实启动、真实链路、真实输入输出）：

```bash
python tools/module_smoke.py     # 全部只读 CLI 逐条真跑（需校园网/VPN 与凭据）
python tools/webui_smoke.py      # 进程内起真实 Flask 服务，逐页断言 200
python tools/pii_scan.py         # 提交前必过：无真实学号等个人信息
```

CI 只跑离线门（装得上、CLI 起得来、SKILL 与 CLI 一致、无 PII）；需要校园网的验证在贡献者本机完成，PR 描述里写清端到端路径（跑了什么、核对什么）。

## 边界

- 写操作仅五条（`canvas submit/reply/send`、`booking book/cancel`），全部带预检或确认门；不新增其他写操作，不做选课、抢课。
- 凭据与真实学号不进仓库、不进 issue。
- 能力变更同步三处：[skills/westlake-survival/SKILL.md](skills/westlake-survival/SKILL.md)、[README](README.md) 功能表、[docs/skill_reference.md](docs/skill_reference.md)。
