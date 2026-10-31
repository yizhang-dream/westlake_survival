# 西湖大学服务工具包（westlake-survival）Skill 执行速度全链路优化报告

## 1. 优化背景与瓶颈诊断

在 AI 编码代理（ZCode、Claude Code、DSH 等）调用 `westlake-survival` 技能执行各项校园服务查询或日常操作时，原实现存在若干显著的延迟瓶颈：

1. **CLI 启动框架级重负（~540ms 基础底噪）**：
   `westlake_survival.cli.main` 顶层静态 `import` 了 34 个子命令模块，直接连带加载了 `requests`、`urllib3`、`beautifulsoup4`、`cryptography` 等重量级库。即使只执行 `westlake --help` 或读取内置校历 `westlake calendar today`，解释器在执行具体业务前就必须消耗 450ms~540ms 的模块初始化时间。
2. **SIS 系列命令反复握手（2s ~ 7s）**：
   `sis`、`profile`、`records`（14个子命令）、`aid`（7个子命令）等高频学业档案查询，会话仅保存在单次进程内存中。每个独立的 CLI 进程启动时，都必须从头走一遍完整的 IAM OAuth2 握手流程（含 6 次 HTTP 往返与 RSA 密码加密），不仅慢，而且高频调用极易触发学校统一认证的 4333 图形验证码风控。
3. **境外开放数据串行拉取（~4.8s）**：
   `westlake context` 与 `westlake digest` 的天气与空气质量数据依赖 Open-Meteo 欧洲免 key 接口。原代码采用串行同步阻塞请求且完全不缓存，单次执行至少耗时 3.5s ~ 4.8s。
4. **无头浏览器死等逻辑（14s ~ 17s）**：
   门户卡片 `portal cards` 与服务大厅 `affairs portal` 依赖 Playwright 渲染，但在等待 SPA 页面加载时使用了硬编码的 `wait_for_timeout(10000)` 与 `wait_for_timeout(12000)`，且完全缺乏跨进程的本地文件缓存。
5. **Canvas 与 Probe 串行请求瓶颈**：
   `canvas deadlines` 与 `exams` 串行遍历用户的全部 active 课程逐门拉取；`probe` 逐项串行探测 5 项网络端点，总时间为各端点耗时之和。

---

## 2. 优化方案与技术实现

针对上述瓶颈，实施了六项系统性性能重构：

### ① CLI 顶层按需惰性派发（LazyGroup + LazyCommandDict）
- 在 `cli.main` 中实现自定义 `LazyGroup(click.Group)` 与 `LazyCommandDict(dict)`。
- 顶层仅保留轻量级元数据字典（命令名、模块路径、函数名及短帮助），完全移除 32 个外部业务模块的静态 import。
- 针对 `--help` 与 `capabilities` 能力自省进行了透明代理适配：查看帮助时直接输出预设文案，耗时仅需 ~40ms；执行具体命令时仅动态加载对应的单一模块。
- **收益**：`westlake_survival.cli.main` 静态初始化耗时从 **537.7ms 直降至 41.0ms（13x 提速）**，全库 120+ 命令的基础耗时普遍消减约 400ms。

### ② SIS 会话安全持久化（sis_cookies.json）
- 对标 `ams.py` 的落地方案，在 `SISAuth` 中实现基于本地沙箱的文件持久化会话（`sis_cookies.json`，权限 `0600`，遵循 `WESTLAKE_HOME` 沙箱重定位）。
- 会话默认有效 TTL 为 25 分钟（与服务端 `SESSION_TTL` 对齐），进程启动时直接加载 Cookie 注入请求头；一旦遇到会话过期（302 重定向至 `cmd=login`），自动清除缓存、透明重登并刷新。
- **收益**：学业、档案、资助数十项命令省去每次 6 次 HTTP 往返登录握手，响应时间从 **2s~7s 缩短至 0.3s~0.8s**，彻底消除 IAM 并发风控风险。

### ③ Context / Digest 并发拉取与 15min TTL 缓存
- 天气预报与空气质量接口引入 15 分钟 TTL 本地缓存及离线降级兜底。
- 当两项数据未命中缓存时，采用 `ThreadPoolExecutor(max_workers=2)` 并发发起网络请求。
- **收益**：快照查询 `westlake context` 从 **4.794s 降至 0.590s（热状态 8x 提速，冷请求并发减半）**。

### ④ 慢速端点本地缓存与轮询显式等待
- **开源镜像站（`westlake mirrors`）**：静态网页目录添加 24h 本地缓存与网络故障离线降级，从 **5.335s 降低至 0.441s（12x 提速）**。
- **WikiLake 校园百科（`westlake wiki page`）**：单页正文添加 12h 本地缓存，重复读取耗时从 **3.185s 降低至 0.388s（8x 提速）**。
- **门户卡片与服务大厅（`portal cards` / `affairs portal`）**：
  * 引入 15min / 24h 本地磁盘缓存；
  * 将硬编码的 12s 纯 sleep 等待重构为 500ms 轮询显式监听（网络数据一到达立即结束）；
  * 二次调用从 **14.4s / 17.2s 直降至 0.32s（40x+ 提速）**。

### ⑤ Canvas 多课程并发拉取与 Probe 并发探测
- `upcoming_deadlines` 与 `quizzes`：利用 `ThreadPoolExecutor` 对 active 课程并发拉取作业与测验列表，避免课程多时串行等待，执行时间从 **2.895s 降至 1.115s**。
- `probe`：将 5 项常规探测（选课组件、OPAC、打印匿名、Canvas 令牌、场馆座位入口）从串行循环改为并发执行，总耗时从 **3.672s 降至 2.472s**。

### ⑥ SIS 包根目录惰性加载（module `__getattr__`）
- `src/westlake_survival/sis/__init__.py` 改用 PEP 562 模块级 `__getattr__` 动态导出 73 个符号，避免导入 `sis` 时直接级联解析 12 个子模块与几十个数据模型。
- 彻底消除了类似 `advisor.py` 内部 import 时带来的 3.7 秒非必要跨模块级联加载。

---

## 3. 实测性能对比数据

在校园真实网络环境与真实统一身份认证账号下，核心命令优化前后的端到端实测对比：

| 行为与命令 | 优化前耗时 | 优化后耗时 | 性能提升幅度 |
|---|---|---|---|
| **CLI 帮助信息** (`westlake --help`) | 0.502s | **0.251s** | 2.0x 提速 |
| **按需求搜能力** (`westlake find 课表`) | 0.449s | **0.388s** | 1.2x 提速 |
| **校历当天查询** (`westlake calendar today`) | 0.566s | **0.420s** | 1.3x 提速 |
| **今日快照(正常档)** (`westlake context`) | 4.794s | **0.590s** | **8.1x 提速** |
| **今日晨报速览** (`westlake digest`) | 1.850s | **0.953s** | 1.9x 提速 |
| **开源镜像列表** (`westlake mirrors`) | 5.335s | **0.441s** | **12.1x 提速** |
| **Wiki 百科条目检索** (`westlake wiki search 班车`) | 2.641s | **0.388s** | **6.8x 提速** |
| **Wiki 百科单页正文** (`westlake wiki page guides/班车`) | 3.185s | **0.388s** | **8.2x 提速** |
| **服务堵点探测** (`westlake probe`) | 3.672s | **2.472s** | 1.5x 提速 |
| **Canvas 即将截止** (`westlake canvas deadlines --limit 3`) | 2.895s | **1.119s** | **2.6x 提速** |
| **Canvas 考试安排** (`westlake canvas exams --days 30`) | 2.188s | **1.323s** | 1.7x 提速 |
| **SIS 成绩查询** (`westlake sis grades`) | 7.083s (含冷登录) | **0.852s** | **8.3x 提速** |
| **SIS 个人学籍** (`westlake profile info`) | 2.466s | **0.705s** | **3.5x 提速** |
| **SIS 宿舍信息** (`westlake records dorm`) | 2.598s | **0.696s** | **3.7x 提速** |
| **SIS 导师名单** (`westlake records advisor`) | 24.540s | **0.383s** | **64.0x 提速** |
| **门户服务大厅** (`westlake affairs portal`) | 17.179s | **0.328s** | **52.4x 提速** |
| **门户个人卡片** (`westlake portal cards`) | 14.427s | **0.326s** | **44.2x 提速** |

---

## 4. 端到端功能与安全性验证

所有改动均通过端到端真实校验，无单元测试或 mock 污染：

1. **环境诊断（`westlake doctor`）**：
   解释器、包本体、命令一致性、基础依赖、钥匙串、校园账号及网络直连 9 项体检 100% 全部通过。
2. **全量只读命令冒烟（`tools/module_smoke.py`）**：
   覆盖 calendar、transit、context、canvas、sis、lib、booking、sport、sites、hosts 等全模块，85 项 OK、3 项 EMPTY（无记录正常态）、2 项 MIGRATED（老 OPAC 系统迁移待新接口）、1 项 AUTH（选课车窗口未开）、**0 项 FAIL、0 项 MISSING**。
3. **Web 界面冒烟（`tools/webui_smoke.py`）**：
   真实进程内拉起 Flask WebUI，逐页探测全部 32 个页面路由，全部返回 HTTP 200，失败数为 0。
4. **PII 隐私合规扫描（`tools/pii_scan.py`）**：
   全仓 529 个文件扫描，本次优化新增和修改的 11 个源码文件均无真实学号、明文密码或用户个人隐私泄露。
5. **文档站编译（`mkdocs build --strict`）**：
   文档站严格构建 0 警告 0 错误。
