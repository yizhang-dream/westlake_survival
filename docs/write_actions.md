# 受控写操作与 Action Card 安全门

写操作在本项目中是例外而非常态：全部收敛在下方 14 项白名单内，统一经 `consequence.py` 事务门拦截。不提供选课、抢课等功能，不绕过任何权限系统（见 [README 设计原则](../README.md)）。

## 确认流程

所有写操作走同一条门禁链路：

```
[用户指令 / Agent Tool Call]
          │
          ▼
┌──────────────────────────────────────────────┐
│        consequence.py 写操作安全层          │
│  - 风险严重度（LOW / MEDIUM / HIGH）        │
│  - 事务描述与影响范围                       │
└──────────────────────────────────────────────┘
          │
          ├────────────────────────────────────┐
          ▼ (若为 --dry-run 模式)              ▼ (若未带 --yes 且无有效凭据)
┌────────────────────────────────┐   ┌────────────────────────────────┐
│  生成结构化 Action Card 预览   │   │  拦截退出（退出码 1）          │
│  计算一次性 Ticket（15分钟有效） │   │  打印 Action Card 凭证卡片     │
└────────────────────────────────┘   └────────────────────────────────┘
          │                                    │
          └─────────────────┬──────────────────┘
                            ▼
              加 --yes 或提供 --ticket 放行
                            │
                            ▼
               Ticket 防重放核销（单次消费）
                            │
                            ▼
               执行底层业务写操作
```

以云打印为例，`westlake pms print 实验报告.pdf --dry-run` 生成的事务预览卡片：

```text
┌────────────────── [事务预览卡片 Action Card: act-38f008] ──────────────────┐
│ 操作类型: pms.print (风险等级: LOW)                                         │
│ 事务描述: 将本地文件上传到联创自助文印云队列并创建待打印作业                                     │
│ 目标对象: 实验报告.pdf (1 份，单面，黑白)                                     │
│ 变更载荷:                                                               │
│   • file: ~/Documents/实验报告.pdf                                    │
│   • copies: 1                                                       │
│   • duplex: 单面                                                      │
│   • color: 黑白                                                       │
│   • page_range: 全部                                                  │
│ 潜在影响: 文件进入学校打印服务器队列（保留一定时长），在终端网点刷卡取件时才发生扣费结算                       │
│ 确认凭据: tk-4191-bf2c (15分钟内有效，单次放行)                                   │
│ 执行指令: 加 --yes 或 --ticket tk-4191-bf2c                               │
└────────────────────────────────────────────────────────────────────────────┘
```

## 写操作矩阵（14 项）

| 操作标识 | 所属系统 | 命令行入口 | MCP 工具 | 风险等级 | 可逆性 | 行为说明 |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| `canvas.submit` | Canvas | `canvas submit` | `canvas_submit` | MEDIUM | 需覆盖 | 提交文件/文本/链接作业至课程侧，教师立即可见 |
| `canvas.reply` | Canvas | `canvas reply` | — | MEDIUM | 否 | 在课程讨论区回帖，全班可见 |
| `canvas.send` | Canvas | `canvas send` | — | MEDIUM | 否 | 发送 Canvas 收件箱私信 |
| `canvas.star` | Canvas | `canvas star` | — | LOW | 是 | 将课程置顶于个人面板收藏夹 |
| `canvas.unstar` | Canvas | `canvas unstar` | — | LOW | 是 | 将课程移出个人收藏夹（不退课） |
| `canvas.upload` | Canvas | `canvas upload` | `canvas_upload` | LOW | 是 | 上传本地文件至个人 Canvas 文件云盘 |
| `canvas.dismiss_todo` | Canvas | `canvas dismiss-todo` | `canvas_dismiss_todo` | LOW | 是 | 模糊/精确匹配待办事项并在线归档/忽略 |
| `pms.print` | 联创文印 | `pms print` | `pms_print` | LOW | 是 | 上传文件至云打印队列，支持份数/单双面/色彩参数 |
| `pms.cancel` | 联创文印 | `pms cancel` | `pms_cancel` | LOW | 否 | 从云打印队列中取消并删除指定未打印作业 |
| `booking.book` | 场地预约 | `booking book` | — | MEDIUM | 是 | 预约研讨室/自习仓，占用公共资源 |
| `booking.cancel` | 场地预约 | `booking cancel` | — | LOW | 是 | 取消已有预约并释放名额 |
| `lib.renew` | 阿法迪图书馆 | `lib renew` | — | LOW | 否 | 在借图书在线续借（限续 1 次） |
| `calendar.export` | 本地日历 | `calendar export` | `calendar_export` | LOW | 是 | 导出课表与行动流为标准 `.ics` 写入本地 |
| `timeline.memo` | 本地行动流 | `timeline add/done/delete` | — | LOW | 是 | 个人备忘增/删/改/勾选全生命周期 |

## 三端入口

CLI 统一支持 `--dry-run`（预览）/ `--yes`（直接放行）/ `--ticket`（凭证放行）三态：

```bash
westlake pms print <file> [--copies N] [--duplex] [--color] [--dry-run|--yes]
westlake pms cancel <job_id> [--dry-run|--yes]
westlake canvas upload <file> [--dry-run|--yes]
westlake canvas dismiss-todo <keyword_or_id> [--dry-run|--yes]
westlake calendar export [-o schedule.ics] [--dry-run|--yes]
westlake timeline delete <memo_id> [--dry-run|--yes]
```

MCP 侧暴露 `pms_stations`、`pms_jobs`、`pms_print`、`pms_cancel`、`canvas_upload`、`canvas_dismiss_todo`、`calendar_export` 等工具，默认以预检计划形式响应，显式传递 `confirm: true` 才执行底层状态变更。

WebUI 侧：`/pms` 页提供云打印任务提交控制台（参数调整、事务卡片预检弹窗）与取消作业；`/timeline` 页提供 `.ics` 导出与备忘的安全删除。

## 验证口径

每项写操作按 `--dry-run` 预览生成、无标志拦截、`--ticket` 消费、防重放二次拦截四步断言；全量回归走 `tools/module_smoke.py` 与 `tools/webui_smoke.py` 端到端真跑，提交前 `tools/pii_scan.py` 扫描敏感信息（本仓库不维护单元测试）。
