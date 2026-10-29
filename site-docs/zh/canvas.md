# Canvas 课程与作业

认证：**优先个人令牌**（网页「设置」可配置或通过 `WESTLAKE_CANVAS_TOKEN` 指定），未配置令牌时自动回退为统一身份认证会话。若遇到 401 鉴权失败，可先检查令牌是否失效或运行 `westlake setup --clear-canvas-token` 清除令牌。

## 只读查询

```bash
westlake canvas courses                    # 课程列表
westlake canvas deadlines                  # 作业与任务截止时间列表
westlake canvas exams                      # 考试与测验
westlake canvas todo                       # 待办
westlake canvas assignment-info --course 概率论 --assignment 作业3 \
       [--download ./dir]                  # 作业详情+题目附件+评分细则
westlake canvas files --course ...         # 课程文件区（可下载）
westlake canvas discussions|announcements|inbox
```

## 受控写操作（consequence 安全拦截）

```bash
westlake canvas submit --course ... --assignment ... --file hw.pdf --dry-run   # ① 预检
westlake canvas submit ... --yes                                            # ② 提交
westlake canvas submission --course ... --assignment ...                     # ③ 回读核验
westlake canvas reply  --course ... --topic ... --text "..." --yes           # 讨论回帖
westlake canvas send   --conversation 123 --text "..." --yes                 # 回私信
```

执行写操作时若未附加 `--yes` 参数，系统会输出包含操作目标、潜在风险与可逆性的结构化说明，并以退出码 1 终止；对已关闭或不可回复的会话（`cannot_reply`）将直接拒绝。作业提交建议按「预检（`--dry-run`）→ 正式提交（`--yes`）→ 状态核验（`submission`）」流程执行。
