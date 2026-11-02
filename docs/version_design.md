# 版本体系与契约设计规范（Version Design & Contract）

> 本规范参考并借鉴 **archify** 的版本治理架构与更新感知协议（Update Awareness），将 `westlake-survival` 的版本体系从早期的按日发布（CalVer）全面升级为标准的**语义化版本（SemVer 2.0.0）**，确立多端元数据单一可信源、严格的版本校验契约与尊重用户控制权的非侵入式更新感知机制。

---

## 1. 演进背景与设计目标

### 1.1 历史背景
在早期开发阶段，本项目参考了 `sustech_survival` 的日期版本风格（CalVer），使用形如 `2026.10.29`、`2026.11.01` 的格式。随着项目演进，该方案暴露出明显的工程局限：
- **语义模糊**：无法区分重大架构重构（Major）、新功能特性扩展（Minor）与日常缺陷修复（Patch）；
- **通道缺失**：无法区分面向日常师生与智能体接入的正式稳定版（`stable`）与面向实验性特性的开发预发布版（`development`）；
- **元数据割裂**：代码库（Python）、智能体技能定义（`SKILL.md`）以及自动化分发清单缺乏机器可读的统一定义契约。

### 1.2 参考 archify 的版本设计
archify 作为高质量的工程化 Agent Skill 典范，在版本管理上具备极为严密的工程设计：
1. **语义化三段式分层**：严格遵循 SemVer 2.0.0 规范；
2. **结构化发布清单**：根目录常驻 `skill-release.json`，声明 schema 版本、skillId、渠道、版本号与更新源；
3. **Skill 元数据对齐**：在 `SKILL.md` 的 YAML frontmatter 中明确标注 `metadata.version`；
4. **版本契约校验（Update Contract）**：提供确定性的版本解析、比较与合法性断言；
5. **非侵入式更新感知（Update Awareness）**：遵循「通知是信息不是授权」原则，绝不自动下载覆盖，支持缓存保护与免打扰管理（snooze/ignore）。

---

## 2. 语义化版本（SemVer 2.0.0）规范

### 2.1 版本号格式
版本号严格遵循：
```text
MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]
```
- **MAJOR（主版本号）**：当发生不兼容的重大接口断裂、底层架构重塑或核心安全策略升级时递增；
- **MINOR（次版本号）**：当新增服务域模块、新增复合求解器或以向后兼容的方式扩展功能时递增；
- **PATCH（修订版本号）**：当进行向后兼容的缺陷修复、抓取规则调整、敏感信息脱敏强化或性能打磨时递增。

### 2.2 首个正式稳定里程碑：v1.0.0
本项目正式确立 **`1.0.0`** 作为首个成熟正式稳定版本。该版本标志着以下全套系统级能力的成熟闭环：
- **时空行动流（Timeline）**：跨系统全天日程融合、冲突预警与本地生活备忘全栈打通；
- **场景级求解器（Solvers）**：研讨室空闲智能推荐（`booking recommend`）与离线优先（SWR 快照）直出；
- **Action Card 事务安全门**：受控写操作矩阵（Canvas 收藏/网盘/待办、联创文印云上传、图书续借）强制经由单次有效 Ticket 审查与防重放放行；
- **现代编译套件 SkillVM**：AOT 编译输出多端框架（ZCode / Claude Code / Cursor / MCP）并实施 Cognitive Profiling 优化；
- **全域服务覆盖**：新版阿法迪云图书馆、三校区生活网点、HPC 免费 AI 对话网关与办事大厅直达；
- **全局敏感信息脱敏（PII Shield）**：学号等隐私数据全局掩蔽。

### 2.3 发行渠道（Channel）划分
- **`stable`（稳定版）**：纯三段数字（如 `1.0.0`），无预发布标识，面向全体师生与生产自动化流推荐使用；
- **`development`（开发版/预发布版）**：包含预发布后缀（如 `1.1.0-dev`、`1.0.1-rc.1`），仅供前沿特性开发与内部验证。

---

## 3. 多端元数据资产与单一可信源

```text
               ┌─────────────────────────────────────┐
               │  src/westlake_survival/_version.py  │
               │   __version__ = "1.0.0"             │
               │   __channel__ = "stable"            │
               └──────────────────┬──────────────────┘
                                  │ Single Source of Truth
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  pyproject.toml  │    │skill-release.json│    │     SKILL.md     │
│ [tool.hatch.ver] │    │ "version":1.0.0  │    │ metadata.version │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

1. **核心单一可信源**：`src/westlake_survival/_version.py` 作为代码层唯一基准，导出：
   - `__version__ = "1.0.0"`
   - `__release_date__ = "2026-11-02"`
   - `__channel__ = "stable"`
   - `VERSION_INFO = VersionInfo(1, 0, 0)`
2. **发布元数据清单**：`skill-release.json`（放置于仓库根目录），供自动化分发工具与智能体平台结构化识别：
   ```json
   {
     "schemaVersion": 1,
     "skillId": "westlake-survival",
     "channel": "stable",
     "version": "1.0.0",
     "source": {
       "repository": "https://github.com/yizhang-dream/westlake_survival"
     },
     "updateManifestUrl": "https://raw.githubusercontent.com/yizhang-dream/westlake_survival/main/skill-release.json"
   }
   ```
3. **Skill 规范定义**：`skills/westlake-survival/SKILL.md` 的 YAML frontmatter 严格对齐元数据：
   ```yaml
   ---
   name: westlake-survival
   description: 面向西湖大学师生的校园服务聚合工具（学业/教学/科研/生活/办事/信息六域）。
   license: PolyForm Noncommercial 1.0.0
   metadata:
     version: "1.0.0"
     author: yizhang-dream
   ---
   ```

---

## 4. 版本契约模块（`version_contract.py`）

借鉴 archify 的 `update-contract.mjs`，在 `src/westlake_survival/version_contract.py` 中实现了严格的版本语义契约：
- **`parse_semver(v)`**：严格按 SemVer 2.0.0 规范解析版本字符串，校验预发布段无非法前导零；
- **`compare_semver(v1, v2)`**：标准比较算法，先比对主/次/修订三元组，再比对预发布标识（无预发布标识的正式版本严格大于带预发布标识的版本，如 `1.0.0 > 1.0.0-rc.1`）；
- **`release_channel_for_version(v)`**：自动判定版本所属渠道；
- **`load_local_release()`**：自动加载并校验本地 `skill-release.json` 的结构完整性与版本渠道一致性。

---

## 5. 版本更新感知与免打扰机制（`update_check.py`）

借鉴 archify 的 Update Awareness 协议，版本更新感知机制遵循以下铁律：

### 5.1 核心原则
1. **通知是信息，绝非权限（Information, Not Permission）**：
   - 发现新版本时仅输出明确的更新提示与升级指引；
   - **严禁**在后台自动下载安装包、执行静默覆盖或强行升级；升级行为完全交由用户或运维代理自主决定。
2. **轻量缓存与非阻塞降级**：
   - 检查结果缓存在 `~/.westlake_survival/update_cache.json` 中，默认 TTL 为 24 小时；
   - 业务命令运行期间绝不频繁发起网络检查；超时控制在 2 秒以内；
   - 网络异常或离线运行时，静默降级为离线状态，绝不抛出异常阻断业务流程。

### 5.2 免打扰协议（Snooze & Ignore）
支持用户与 Agent 针对更新提示进行细粒度控制：
- **`westlake update-snooze [--days 7]`**：将当前检测到的新版本提醒推迟 7 天，期间不再弹出提示；
- **`westlake update-ignore`**：永久忽略当前特定版本的提示，直到上游发布更高版本。

### 5.3 交互集成
- **`westlake version`**：
  - 常规展示当前安装版本、发布日期、渠道与代码仓库；
  - 传入 `--check` 可强制发起联网检查；
  - 传入 `--json` 输出结构化版本字典。
- **`westlake doctor`**：
  - 体检矩阵包含「版本契约与更新」检查项，发现新版本时显示为黄色提醒并给出升级命令；当前为最新版或离线时显示为绿色通过，保证体检退出码保持为 0，不破坏自动化断言。
