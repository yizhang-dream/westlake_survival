# 模块体检（第二轮）：把「跑通一次」换成「逐个模块验过」

2026-10-27。起因：预约中心的主链路跑通之后，才发现权限、占位外链、服务端未配置
三件事都藏在主链路之外。同样的形态在别的模块里必然存在，所以这次不再靠「谁想
起来看一眼」，而是做两层机制 + 并行实测。

## 一、方法：两层，缺一不可

**第一层：冒烟矩阵（可重复）**

```bash
python tools/module_smoke.py            # 全部只读命令，约 3-8 分钟
python tools/module_smoke.py sis canvas # 只跑匹配模块
python tools/module_smoke.py --json /tmp/smoke.json
```

覆盖 51 条只读命令，逐条判定 `OK / EMPTY / AUTH / FAIL / MISSING`。
基线（2026-10-27）：

- **OK 44、EMPTY 7、FAIL 3**；
- 3 条 FAIL 全部指向已知堵点：OPAC 404、图书馆 CAS 401、打印会话未登录；
- 7 条 EMPTY 里混着真正常空与「解析失效」——这正是第二层要分辨的。

**第二层：按模块深审**

每个模块由独立审计员执行同一个动作序列：

1. 读 SKILL.md 与模块 docstring 里的「实测」承诺；
2. 真跑命令（只读），记录退出码与前几行；
3. 判定：`文档对/静默空/权限/接口变/真不可用`；
4. 定位到 `文件:行号`，写清修复方向。

判定标准只有一条：**空结果必须能区分「真的没有」「没权限」「接口挂了」**。
三者呈现相同，就是缺陷。

## 二、本轮查出的东西

### 1. SIS 界面改中文后，9 条命令静默失效（最严重）

站点语言从英文切到中文，只有 `grades.py` 在 10-24 用「双语列名」修过，其余仍在
按英文表头解析，于是：

| 命令 | 实际 | 之前表现 |
| --- | --- | --- |
| `sis exams` | 页面 10 行考试 | 「考试安排为空」exit 0 |
| `sis-evals list --pending` | 页面 25 行（全部已提交） | 「无评估任务」 |
| `records dorm` | 3 条申请 | 全「—」 |
| `records volunteer` / `vol-history` | 4 行真实数据 | 全「—」，总时长「—」 |
| `records advisor` | 246 位导师 | 姓名/名额/志愿全空 |
| `aid loans\|jobs\|outbound\|exchange\|activities` | 中文空文案页 | 直接 ParseError，五条挂五条 |

修法：把 `grades.py` 的双语列名模式复制到 exams/evals/records/advisor；`aid` 补中文
空文案 marker；`COMPLETED_STATUSES` 补 `Submit` / `已提交`。**同时改语义**：页面有
数据行但具名字段全空时不再静默跳过，改为抛 `ParseError` 并列出已识别列——防止下次
改版再静默丢数据。

> 验证状态：解析层已按真实页面数据修好，并做了「伪造未来表头必抛错」的演练；
> CLI 级复验被下面的 IAM 风控挡住，待解除后重跑这 13 条。

### 2. Canvas：截止日在一周以外全部漏报

`upcoming_deadlines` 只取 `bucket=upcoming`（Canvas 该桶只含未来约 7 天），实测 2 条
vs 实际 6 条（11-27、12-13、次年 01-28 三条凭空消失）。这条缺陷同时污染 CLI、
`digest` 晨报、MCP、WebUI、`context` 五个入口。

修法：合并 `upcoming` + `future` 两桶并按 id 去重。**已实测**：现在返回 6 条，
含 2027-01-28。

另外 `list_courses` 不请求 `include[]=term`，课程列表「学期」列恒空。已修，
现在显示 `2026 FALL`。

### 3. 内容站：静默降级比报错更危险

| 缺陷 | 位置 | 形态 |
| --- | --- | --- |
| 抓取失败伪装成正常简介 | `sites.py` `site_content` | sections 为空时无条件写「办事型站点…入口直达」，异常只打 stderr、exit 0 |
| 信封缺键静默返回空 | `search.py` `parse_search` | docstring 说抛 ParseError，实现却 `[]`；官网改键名会永远「未找到匹配的内容」 |
| 列表不按时间排序 | `research.py` `latest()` | 按官网分组展平后直接截断，「最新 5 条」其实是首组前 5 条 |
| 代表作把「联系我们」算进去 | `faculty.py` `_parse_representatives` | 计数 2 项，实际 5 篇论文 + 1 个联系块 |

四处均已修并实测：`sites site` 失败时 exit 1；`research --limit 5` 首条为
2025-11-14；`faculty detail` 代表作不再含联系块。

### 4. 办事门户：异常直接甩 traceback

`westlake affairs portal` 在门户接口结构变化时抛 `WestlakeError` 但没接，
用户看到的是一屏堆栈。已改为一行错误 + exit 1。

## 三、操作教训：并发审计会踩 IAM 风控

本轮同时开 6 个审计员 + 一个冒烟矩阵，全部用同一账号登录，结果：

- 多个进程并发登录后，IAM 返回 `4333（验证码或登录名为空）`，期间还出现
  `4020 已认证失败 N 次`计数；
- 等待 45 分钟后重试仍是 4333；`verifyCodeIsNeed` 返回 `None` **不能**作为
  「没被风控」的判据——`authExecute` 照样拒绝；
- 后果：13 条 SIS 命令的 CLI 复验全部挡住，只能等风控窗口过去。

写进规则的几条：

1. **认证类审计串行**：同一账号同时最多 2 路；冒烟矩阵与审计不要并行跑。
2. **失败一次即停**：看到 4333 / 验证码文案就停手，不重试——重试只给计数续期。
3. **`verifyCodeIsNeed` 只说明「当前这张表单要不要验证码」**，不代表账号没被限流。
4. 免凭据模块（内容站、培养方案、财务、镜像）可以并行，不受此限。

## 四、还没做完的

| 模块组 | 状态 | 原因 |
| --- | --- | --- |
| 预约中心 / 场馆 / 图书馆 / 打印 | 未跑 | 需 IAM 登录，风控中 |
| 校历 / 班车 / 办事 / 门户 / VPN | 未跑 | 部分需 IAM；`affairs portal` 已单独修 |
| 学术资源 / HPC / 财务 / 镜像 | 审计代理运行中 | 免凭据为主 |
| 教务（SIS 13 条） | 代码已修，CLI 未复验 | IAM 风控 |

解除风控后的第一件事：

```bash
westlake sis exams && westlake sis-evals list --pending && \
westlake records volunteer && westlake records advisor && westlake aid loans
```

预期：exams 出 10 行、pending 为 0（25 条已提交）、volunteer 4 行、advisor 246 行、
aid 各返回空列表而不是报错。

## 五、这套机制怎么继续用

- 改任何模块的解析层：先跑 `python tools/module_smoke.py <模块>` 留基线，改完再跑一次对比。
- 加新模块：在 `tools/module_smoke.py` 的 `COMMANDS` 里加一条只读命令，否则它永远不会被体检。
- 每条新命令的自检问题只有一个：**这条命令返回空的时候，我能不能说清是哪种空。**
