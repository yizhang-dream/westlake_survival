# 校园接口要求

入口见 [README](README.md)。本项目自带 ZCode 项目级技能 `westlake-survival`（[.zcode/skills/westlake-survival/SKILL.md](.zcode/skills/westlake-survival/SKILL.md)，2026-10-24 从 `skills/` 迁入发现根）：新会话可用 `/westlake-survival` 调用；CLI/MCP/WebUI 能力变更时同步更新该 SKILL.md。仅访问用户本人有权的数据，不绕过权限、抢课或擅自写学校系统。live 查询与写操作须在任务授权和凭据范围内；离线 fixture、缓存与真实服务结果分别说明。

凭据和会话不打印、记录或提交，只报来源有无。Windows 明文文件不能仅凭0600宣称安全。保留许可、第三方署名与事实数据来源。

## HTML 输出与发布规范（用户裁定 2026-10-11）

<!-- html-delivery-spec v20261011c -->
- 有实质内容的回复（结论/总结/计划/对比/审查/解释/多节内容）渲染成 HTML 单页交付，不写 markdown 长文；闲聊、一两句话、纯命令输出、用户点名纯文本时不用。
- Desktop 用 ::visualize fragment 内联；发布页发到 `https://answers.离命塔.cn/<yyyy-mm-dd>-<slug>.html` 并 curl 验 200，**新页必须登记进 answers 目录页 index.html**；聊天只给公网 URL，不以本地路径作为最终交付。
- 发布页统一 v3 皮肤：head 引 `base.css?v=20261011c` + `motion.js?v=20261011c`（defer），data-reveal 入场、只用令牌色（light-dark() 自动明暗）、SVG 数据 URI favicon、语义骨架 .page/.card/.callout/.btn/.badge/table；改共享资源必升 ?v= 并同步记忆。最小模板：https://answers.离命塔.cn/2026-10-11-apple-style-standard.html
- 图解（架构/流程/时序/数据流/生命周期）优先 archify；问答/正文页用 am.mjs（~/.zcode/skills/answer-me-with-html），不手写 HTML/CSS/SVG。
- 含密钥/token/私密代码的页面发布前先脱敏或标注。

<!-- proactive-work-style v20261012b -->

## 积极行为准则（2026-10-12 用户裁定）

已授权目标内的事主动做完：显然的下一步直接做，可逆动作不重复请示，把「要不要做」换成「做完汇报」。遇到障碍先换方法、先完成不受影响的部分，再如实说明剩余缺口。给用户选项时带自己的推荐，不做开放式甩问。结束前自查目标完成度与结果核验，能当场补的当场补。

持续推进（2026-10-12 追加）：已点火的工作线每次推进都不自动停止，连续做完下一步与再下一步；只有两种情况停下等用户：出现需要用户决策的事，或确实无从下手。训练/批任务跑着时，等待期用来推进能并行的下一项。
