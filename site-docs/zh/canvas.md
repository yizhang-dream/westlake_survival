# Canvas 课程与作业

认证：**优先个人令牌**（网页「设置」可存/清，`WESTLAKE_CANVAS_TOKEN` 亦可），无令牌自动回退统一密码会话。报 401 先怀疑过期令牌：`westlake setup --clear-canvas-token`。

## 只读查询

```bash
westlake canvas courses                    # 课程列表
westlake canvas deadlines                  # 全部截止（不限 7 天窗口）
westlake canvas exams                      # 考试与测验
westlake canvas todo                       # 待办
westlake canvas assignment-info --course 概率论 --assignment 作业3 \
       [--download ./dir]                  # 作业详情+题目附件+评分细则
westlake canvas files --course ...         # 课程文件区（可下载）
westlake canvas discussions|announcements|inbox
```

## 三类写操作（consequence 确认门）

```bash
westlake canvas submit --course ... --assignment ... --file hw.pdf --dry-run   # ① 预检
westlake canvas submit ... --yes                                            # ② 提交
westlake canvas submission --course ... --assignment ...                     # ③ 回读核验
westlake canvas reply  --course ... --topic ... --text "..." --yes           # 讨论回帖
westlake canvas send   --conversation 123 --text "..." --yes                 # 回私信
```

未加 `--yes` 时打印结构化风险描述（改什么/风险/严重度/可逆性）并退出 1；`cannot_reply` 的会话直接拒绝。交作业建议三步走：预检 → `--yes` 提交 → 回读核对。
