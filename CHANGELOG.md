# 更新日志（Changelog）

本项目所有重要变更均记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号严格遵循 [语义化版本 2.0.0 (SemVer)](https://semver.org/lang/zh-CN/) 规范，参考 archify 的版本体系与契约设计。

---

## [Unreleased]

### 验证体系（Testing Infrastructure）
- **冒烟矩阵分层精选（Smoke Tiering）**：`tools/module_smoke.py` 的 141 条只读命令按「依赖什么」打标分三层——匿名（公开网页/接口）、`offline`（随包快照与本地计算，连网都不用）、`auth`（凭据/登录态/个人数据/校园网，68 条）。**默认只跑不依赖账号的 73 条精选集**（实测 73/73 OK），`--auth` 显式跑凭据组、`--offline` 单选纯离线子集、`--all` 全量、`--list` 只列清单不执行；`--json` 输出新增 `tags` 字段（向后兼容）。混在匿名区的登录态命令（`career deep`、`share files`、`scholar status`）归位到凭据组；
- **参数自举（Bootstrap）：`--auth` 组不再绑具体账号的内容**——每个人账号里的课程、作业、讨论主题、会话、可约资源、已登记分享都不同，写死样例（「概率论」「Quiz 1」「会话 2041」「E12-302研讨室」）换账号必挂。带 `{占位符}` 的 16 条命令在执行前先跑取数命令、从**当前账号**的真实列表提取第一项替换（课程传 id 避开同名课歧义；「第一门有作业/讨论的课」最多扫 12 门，不取盲第一门）；日期 `{today}`/`{tomorrow}`/`{today+6d}` 运行日动态生成；该账号无此类内容标 `SKIP`（新增判定态，不算失败）。实测 canvas/booking/sport/share 26 条：24 OK + 2 EMPTY（合法空），自举命中「Assignment 01」等真实参数而非旧样例；
- **CI 离线门升级**：新增 `python tools/module_smoke.py --offline` 步骤（10 条纯离线命令真出结果），从「CLI 起得来」升级为「离线命令真跑通」；
- **WebUI 冒烟口径说明**：`tools/webui_smoke.py` 明确不依赖账号凭据——需登录页面在无凭据环境走降级路径仍断言 200，任何机器可跑。

## [1.0.0] - 2026-11-02

### 核心功能集成（Features）
- **组织内 SharePoint / OneDrive 深度贯通（Org SharePoint Support）**：
  - **组织会话管理**：新增 `sharepoint_storage.json` 安全凭据层（0600 权限、只存本机不跨端），原生兼容 Playwright storage_state 架构；
  - **登录命令矩阵**：新增 `westlake share login`（支持弹窗交互式登录与 `--cookie` 免弹窗纯文本注入）、`westlake share auth-status`（状态查看）与 `westlake share logout`（安全登出）；
  - **无缝鉴权穿透**：`ShareBrowser` 自动加载组织凭据，打通何彬老师 Capstone 等设为「组织内限制」的 SharePoint 讲义目录与下载直链，遇未登录或过期提供精准命令行引导；
- **集成过往结课课程（Past Courses Integration）**：
  - **CanvasClient 深度拓展**：`list_courses(state=...)` 与 `course_grades(state=...)` 全面支持在修（`active`）、过往结课（`completed`）及全部（`all`）模式，新增 `list_past_courses()` 快捷接口；
  - **课程名称检索自动回退**：`find_course(keyword)` 在未命中当前在修课程时，智能自动回退匹配过往结课课程，彻底解决 `canvas files --course <过往课名>` 找不到课程的问题；
  - **CLI 控制台升级**：`westlake canvas courses` 增加 `--past` / `--all` / `--state` 开关，清晰输出课程 ID、学期与在修/结课状态，新增 `westlake canvas grades` 支持查看各学期成绩；
  - **WebUI `/canvas` 视窗升级**：增加「过往课程」专区，按 2026 SUMMER、2026 SPRING、2025 FALL 等历史学期结构化归档展示，卡片一键直达 Canvas，顶部数据条同步纳入过往结课计数；
  - **MCP 协议支持**：注册全新 `canvas_courses` 工具，支持状态与关键词过滤，赋能智能体自主调取与研读过往课程资料。

### 架构演进与版本契约（Architecture & Version Contract）
- **确立语义化版本（SemVer 2.0.0）体系**：
  - 参考 archify 的版本设计，从早期日期版本（CalVer）全面确立为具备清晰语义分层的正式成熟版本 `1.0.0`；
  - 根目录引入 `skill-release.json`，结构化声明发行渠道（`stable`）、契约版本号与更新清单 URL；
  - `skills/westlake-survival/SKILL.md` 的 YAML frontmatter 规范对齐 `metadata.version: "1.0.0"`；
  - 核心模块引入 `version_contract.py`（版本契约解析与校验）与 `update_check.py`（非侵入式版本更新感知）；
  - `westlake doctor` 与 `westlake version` 全面集成版本状态感知，支持 `--snooze`（推迟 7 天）与 `--ignore`（忽略特定版本）免打扰协议，恪守“更新是信息不是授权、不静默下载不强制覆盖”。

---

## [2026.11.01] - 2026-11-01

### 优化与修复（Fixed & Improved）
- **PII 安全脱敏强化**：
  - `westlake records registration` 与 `dorm` 全局接入学生敏感信息脱敏过滤器（`_mask_sensitive_value`），学号脱敏为 `2025****009`，严格杜绝真实个人敏感信息在控制台和自动化流中泄漏；
  - 全量合规扫描 `tools/pii_scan.py` 严格校验通过。
- **就业服务网详情与容错升级**：
  - `westlake career detail` 增强过期数字条目诊断引导，避免因往期宣讲会下架抛出硬错误；
  - `tools/module_smoke.py` 测试用例固化为官方常设招聘指南（`zpxz`），提升自动化体检矩阵长期稳定性。
- **研讨室智能推荐与别名模糊匹配**：
  - `westlake booking recommend` 与 `booking list` 引入分类别名与模糊匹配（如 `研讨室` 自动映射至 `讨论室` 及图书中心各研讨室、`会议室`、`健身` 等）；
  - 彻底解决用户输入习惯与教务内部分类命名不一致导致的预约权限报错痛点。
- **时空行动流（Timeline）全栈联动闭环**：
  - WebUI 仪表盘 `/timeline` 页面增加备忘条目在线一键删除交互（`/api/timeline/memo/delete`）；
  - MCP 服务端补全 `timeline_delete_memo` 工具规范，打通智能体全生命周期闭环。

---

## [2026.10.31] - 2026-10-31

### 新增（Added）
- **离线优先架构（Stale-While-Revalidate）**：
  - 核心只读模块（课表、校历周次、班车时刻、Canvas 待办）引入带时间戳的本地快照持久化；
  - 弱网、地下室、或在校外未开启 VPN 时自动降级展示本地快照并标注时间戳；全链路支持 `--offline` 参数。
- **场景级复合求解器（Composite Solvers）**：
  - `westlake booking recommend`：智能推荐连续空闲场地，单次请求求解可用时段与预检命令，替代多次原子轮询；
  - `westlake timeline`：今日时空编排行动流，跨系统融合全天课表、Canvas DDL 倒计时、场地预约、校车接驳与本地备忘，自动检测日程重叠时间冲突；Web 仪表盘常驻 `/timeline` 页面。
- **事务预览卡片（Action Card）机制**：
  - 受控写操作未确认或 `--dry-run` 模式下生成结构化的 Action Card 预览，呈现变更载荷明细、安全风险等级与单次有效 Ticket 凭证；
  - 支持传入 `--ticket <ticket>` 单次放行并防重放销毁，避免用户或 AI Agent 重新拼接长命令出错。
- **扩展受控写操作**：
  - `westlake canvas star <课程>` / `canvas unstar <课程>`：Canvas 课程收藏置顶与移除；
  - `westlake lib renew <条形码>`：阿法迪云图书馆在借图书在线续借延期（带到期与可续借校验）；
  - `westlake timeline add <内容> [--time ...]` / `done <ID>`：本地日常生活备忘的新增与完成。
- **SkillVM 现代编译器体系**：
  - 借鉴系统编译器架构（IR -> AOT 目标代码生成 -> JIT 运行时优化）；
  - AOT 编译器支持输出 ZCode、Claude Code、Cursor、MCP 四大框架产物；
  - 引入 Model Profiling 认知优化 Pass（`-O0` 强推理 Frontier、`-Os` 紧凑 Compact、`-O3` 微内核 Micro，Token 占用降低 80%）；
  - 提供 `westlake skill install --target all` 跨机一键挂载工具，彻底消灭单机绝对路径绑定。
- **新版图书馆与生活网点**：
  - 对接阿法迪云平台（`mylib.westlake.edu.cn`），恢复 `lib search`（公开书目检索）与 `lib loans`（在借图书与应还查询）；
  - 新增 `westlake campus services`，覆盖超市、快递驿站、干洗、理发、文印与银行等三校区网点。
- **Canvas 原生精确倒计时列**：
  - 在 `canvas deadlines` 与 `canvas todo` 中引入基于东八区的实时剩余时间列（如 `1 小时 33 分钟后`）。

### 优化（Changed）
- 规范全库文档命名，去除历史会话与过程性日期后缀（`library.md`, `sports.md`, `module_audit.md`, `performance.md`, `portability.md`）；
- 升级 `AGENTS.md`、`README.md` 与 `README_en.md` 的架构原则与使用指南。

---

## [2026.10.29] - 2026-10-29

### 新增（Added）
- **首发 PyPI 分发**：支持 `pip install westlake-survival` 直接安装运行；
- **四端统一入口**：Python 进程内 API、命令行 CLI、本地 Web 仪表盘与 MCP 服务端；
- **单一凭据存储（Single Store）**：优先使用系统钥匙串，写入时互斥清理明文文件，凭据只在本机不跨端；
- **环境体检诊断器**：提供 `westlake doctor`（支持 `--json` 输出），全方位检查解释器、依赖、账号与网络连通性。
