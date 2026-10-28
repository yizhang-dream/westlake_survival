# 凭据只存一份：根除「密码明明对却一直报错」

**日期**：2026-10-27　**提交**：`d69e0ca` → 本次简化

## 事故与根因

本机曾同时存在两份持久凭据：系统钥匙串（8 位学号，**错的**）与明文
`credentials.txt`（11 位学号，对的）。读取优先级 keyring > 文件，**先命中即返回**，
于是正确的那份永远读不到，每次登录都报 `IAM 4020 用户名或密码错误`——而且会长期如此：
错误信息误导人反复试密码，试错又累积 IAM 失败计数触发图形验证码（14h+ 不复位）。

根因不是"缺少比对与告警"，而是**允许多份持久存储同时存在**。

## 修法：只留一份

`westlake_survival.sso.creds.persist_credentials` 是唯一落盘入口，规则只有两条：

1. 写钥匙串成功 → **删除** `credentials.txt`；
2. 只能写文件（keyring 不可用，或用户用 `--no-keyring`）→ **清掉**钥匙串条目。

于是任何时刻最多只有一份凭据在生效，**不存在"高优先级旧值遮蔽低优先级新值"**。
`cred_set`（进程内）与 `WESTLAKE_CREDENTIALS`（进程级覆盖）只影响当前进程，
不落盘、不会跨会话残留。

隔离保护（2026-10-28 收紧）：`WESTLAKE_NO_KEYRING=1`（测试/自动化）与临时
`WESTLAKE_HOME` **两者之一**成立即进入沙箱——钥匙串读写一起跳过，只写文件、
**绝不改动本机真实钥匙串**。判定集中在 `sso.creds.keyring_isolated()`，读、
写、删三条路径共用同一判据。

### 2026-10-28 事故：沙箱只认了「关钥匙串」，没认「临时目录」

仓库里一条 `sso creds set` 用例只重定位了 `WESTLAKE_HOME`，没设
`WESTLAKE_NO_KEYRING`。本机装着 keyring 时，缺省分支照旧把假账号
`20210000` 写进了真实凭据管理器（`service=westlake_survival`，含指向它的
`__westlake__` 指针）。后果与 2026-10-27 那次同型：真实登录先读到假凭据，
一直报「密码错误」，`sso creds status` 还显示「钥匙串里有凭据」。

根因是 `persist_credentials` 里 `real_home` 这个判断只用在「删钥匙串」分支，
没管「写钥匙串」分支——注释写了「临时 WESTLAKE_HOME 一律只写文件」，代码没做到。
修法：把判定提成 `keyring_isolated()`，写分支也用它；测试夹具（`isolated_home`）
另外钉住 `WESTLAKE_NO_KEYRING=1`，两道防线互不依赖。

回归用例：`src/test/creds_sandbox/test_creds_sandbox_e2e.py`——真实子进程跑
`westlake sso creds set`（只设 `WESTLAKE_HOME`，不设 `NO_KEYRING`），核对
临时目录落盘、真实钥匙串条目与指针前后一致。

## 实测（端到端）

| 场景 | 结果 |
| --- | --- |
| 钥匙串 → 文件 | 文件写入成功、钥匙串条目已清、读取仍拿到 11 位学号 |
| 文件 → 钥匙串 | 钥匙串写入成功、明文文件已删、读取正常 |
| 临时 `WESTLAKE_HOME` + 隔离变量 | 只写临时目录文件，真实钥匙串保持「有」 |
| 默认路径 `westlake sso login` | 登录成功（SIS 会话建立） |
| 隔离模式 `status` | 如实显示「keyring：已忽略」，不虚报来源 |

## 机器上如果还留着两份

跑一次 `westlake setup`（或 `westlake sso creds set`）即可收敛成一个——
写入动作会顺手清掉另一份。
