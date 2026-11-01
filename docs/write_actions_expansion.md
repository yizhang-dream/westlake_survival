# 西湖大学生存手册受控写操作矩阵扩充与落地报告

> 日期：2026-11-02  
> 项目：westlake-survival (西湖大学生存手册)  
> 责任：技术架构组 / Agent 运维  
> 状态：全线闭环并经端到端验证通过  

---

## 1. 背景与现状归因

在西湖大学生存手册（`westlake-survival`）早期演进中，系统建设重心集中在跨 90 余个校内业务系统的全景探测、多源日程（SIS、AMS、Canvas、场地、班车）的只读融合与离线 SWR 缓存。

在此之前，系统受控写操作（Mutative Operations）仅登记并实现了 **9 项**，且大部分局限在 Canvas 作业提交与基础研讨室预约。在师生日常真实高频场景中，存在显著的「能查不能办」痛点：
1. **自助文印系统（PMS 联创云打印）**：底层虽然实现了文件上传与删除方法，但未接入安全确认层，CLI、MCP 与 WebUI 均只提供只读的网点和作业查看，学生无法快捷上传文档或取消错传任务；
2. **Canvas 个人学习资产**：师生拥有个人云盘配额（/users/self/files），但之前仅允许上传作业附件，缺少向个人云盘直接存盘的指令；同时过期的待办事项无法直接在线归档/忽略；
3. **时空日程与个人行动流**：课表与融合行动流导出为系统日历（`.ics`）缺少规范的本地写操作门禁与统一命令入口；备忘删除未受 Action Card 凭证拦截保护。

经过系统性需求梳理与权限边界界定，我们在严格坚守**「仅访问本人有权数据、严禁代选/抢课、写操作严格由 Action Card 安全门守卫」**的前提下，正式落地了 5 项全新写操作，使全系统受控写操作总数扩充至 **14 项**。

---

## 2. 安全设计与 Action Card 门禁机制

为防止 Agent 误触写操作或自动化脚本发生非预期状态变更，所有写操作遵循统一的四级安全防御机制：

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
               执行底层业务写操作（真跑）
```

### Action Card 真实预览示例

以自助文印上传为例，执行预检命令 `westlake pms print README.md --dry-run` 会生成如下规范凭证卡片：

```text
┌────────────────── [事务预览卡片 Action Card: act-38f008] ──────────────────┐
│ 操作类型: pms.print (风险等级: LOW)                                         │
│ 事务描述: 将本地文件上传到联创自助文印云队列并创建待打印作业                                     │
│ 目标对象: README.md (1 份，单面，黑白)                                         │
│ 变更载荷:                                                               │
│   • file: D:\westlake_survival\README.md                            │
│   • copies: 1                                                       │
│   • duplex: 单面                                                      │
│   • color: 黑白                                                       │
│   • page_range: 全部                                                  │
│ 潜在影响: 文件进入学校打印服务器队列（保留一定时长），在终端网点刷卡取件时才发生扣费结算                       │
│ 确认凭据: tk-4191-bf2c (15分钟内有效，单次放行)                                   │
│ 执行指令: 加 --yes 或 --ticket tk-4191-bf2c                               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 全量受控写操作矩阵（14 项）

| 操作标识 | 所属系统 | 命令行入口 | MCP 工具 | 风险等级 | 可逆性 | 业务行为说明 |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| `canvas.submit` | Canvas | `canvas submit` | `canvas_submit` | MEDIUM | 需覆盖 | 提交文件/文本/链接作业至课程侧，教师立即可见 |
| `canvas.reply` | Canvas | `canvas reply` | — | MEDIUM | 否 | 在课程讨论区回帖，全班可见 |
| `canvas.send` | Canvas | `canvas send` | — | MEDIUM | 否 | 发送 Canvas 收件箱私信 |
| `canvas.star` | Canvas | `canvas star` | — | LOW | 是 | 将课程置顶于个人面板收藏夹 |
| `canvas.unstar` | Canvas | `canvas unstar` | — | LOW | 是 | 将课程移出个人收藏夹（不退课） |
| **`canvas.upload`** | Canvas | `canvas upload` | `canvas_upload` | LOW | 是 | **[新增]** 上传本地文件至个人 Canvas 文件云盘 |
| **`canvas.dismiss_todo`** | Canvas | `canvas dismiss-todo` | `canvas_dismiss_todo` | LOW | 是 | **[新增]** 模糊/精确匹配待办事项并在线归档/忽略 |
| **`pms.print`** | 联创文印 | `pms print` | `pms_print` | LOW | 是 | **[新增]** 上传文件至云打印队列，支持份数/单双面/色彩参数设置 |
| **`pms.cancel`** | 联创文印 | `pms cancel` | `pms_cancel` | LOW | 否 | **[新增]** 从云打印队列中取消并删除指定未打印作业 |
| `booking.book` | 研讨室 | `booking book` | — | MEDIUM | 是 | 预约研讨室/自习仓，占用公共资源 |
| `booking.cancel` | 研讨室 | `booking cancel` | — | LOW | 是 | 取消已有的研讨室预约并释放名额 |
| `lib.renew` | 阿法迪图书馆 | `lib renew` | — | LOW | 否 | 在借图书在线续借（限续 1 次） |
| **`calendar.export`** | 本地时空 | `calendar export` | `calendar_export` | LOW | 是 | **[新增]** 导出课表与行动流至标准 `.ics` 文件写入本地 |
| **`timeline.memo`** | 本地行动流 | `timeline add/done/delete`| — | LOW | 是 | **[强化]** 个人日程生活备忘增/删/改/勾选全生命周期门禁闭环 |

---

## 4. 三端（CLI / MCP / WebUI）能力对齐

### 4.1 CLI 命令行人体工程学
- `westlake pms print <file> [--copies N] [--duplex] [--color] [--dry-run|--yes]`
- `westlake pms cancel <job_id> [--dry-run|--yes]`
- `westlake canvas upload <file> [--dry-run|--yes]`
- `westlake canvas dismiss-todo <keyword_or_id> [--dry-run|--yes]`
- `westlake calendar export [-o schedule.ics] [--dry-run|--yes]`
- `westlake timeline delete <memo_id> [--dry-run|--yes]`

### 4.2 MCP 服务器暴露
在 `mcp_server.py` 中新增 `pms_stations`、`pms_jobs`、`pms_print`、`pms_cancel`、`canvas_upload`、`canvas_dismiss_todo`、`calendar_export` 等 7 个新工具，参数均采用严格的标准 Schema 校验，且默认以预检计划形式响应，显式传递 `confirm: true` 才执行底层状态变更。

### 4.3 WebUI 前端可视化支持
- `/pms` 页面：任务列表新增「取消作业」交互，新增「云打印任务提交控制台」，支持参数调整、前端事务卡片预检弹窗与一键提交；
- `/timeline` 页面：右上角新增「📅 导出日历 (.ics)」快捷下载通道，备忘列表支持无刷新勾选与安全删除。

---

## 5. 验证与验收结论

1. **写操作门禁端到端跑测**：所有新增写操作均通过 `--dry-run` 预览生成、无标志拦截、`--ticket` 消费与防重放二次拦截四项严格断言；
2. **全系统冒烟体检**：`python tools/module_smoke.py` 120 余条命令全量通过，`westlake find` 自动索引并呈现全部新增写能力；
3. **WebUI 状态检查**：`python tools/webui_smoke.py` 实现全部 33 个核心页面 HTTP 200 断言通过，无死链；
4. **隐私与代码纯洁度**：`python tools/pii_scan.py` 扫描全仓 548 个文件，未引入任何真实学号、个人手机号或密码凭据。
