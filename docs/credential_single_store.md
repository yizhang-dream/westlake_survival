# 凭据单存储机制：避免多处凭据冲突与失效

**日期**：2026-10-27　**提交**：`d69e0ca` → 本次简化

## 问题背景与根因

系统曾存在同时保留两份持久化凭据的情况：系统钥匙串（旧凭据）与本地明文
`credentials.txt`（新凭据）。由于读取策略为钥匙串优先且命中即返回，
导致系统持续读取失效的旧凭据，并在登录时返回 `IAM 4020 用户名或密码错误`。
反复重试还会累积失败计数并触发验证码锁定。

该问题的根本原因在于允许多个持久化存储介质并存且状态不同步。

## 设计实现：单一存储保证

`westlake_survival.sso.creds.persist_credentials` 是凭据持久化的唯一入口，遵循互斥规则：

1. 成功写入钥匙串后，主动删除 `credentials.txt`；
2. 降级写入文件时（如钥匙串不可用或传入 `--no-keyring`），主动清理钥匙串中的历史条目。

确保任意时刻全局仅有一处持久化凭据生效，消除优先级遮蔽导致的旧凭据残留。
`cred_set`（进程内）与 `WESTLAKE_CREDENTIALS`（环境变量覆盖）仅作用于当前进程生命周期，
不产生跨会话持久化副作用。

隔离保护（2026-10-28 收紧）：设置 `WESTLAKE_NO_KEYRING=1`（测试/自动化）与临时
`WESTLAKE_HOME` **两者之一**成立即进入沙箱——钥匙串读写一起跳过，只写文件，
**绝不改动本机真实钥匙串**。判定集中在 `sso.creds.keyring_isolated()`，读、
写、删三条路径共用同一判据。

### 临时目录与钥匙串沙箱隔离机制

在测试环境中，若用例仅通过重定向 `WESTLAKE_HOME` 指定临时目录，而未显式指定
`WESTLAKE_NO_KEYRING`，在安装有 keyring 的环境下，默认写入逻辑可能会将测试占位学号
`2025XXXXXXX` 写入系统真实的凭据管理器（`service=westlake_survival`，含指向它的
`__westlake__` 指针）。这会导致后续常规登录优先读取到测试凭据，引发密码错误。

排查发现，`persist_credentials` 中对 `real_home` 的校验此前仅覆盖了清理分支，
未能严格拦截写入分支。修复方案将隔离判定抽象为统一的 `keyring_isolated()` 函数，
读、写、删分支统一使用该判据；同时测试夹具（`isolated_home`）另外配置
`WESTLAKE_NO_KEYRING=1`，形成双重防线。

回归用例：`src/test/creds_sandbox/test_creds_sandbox_e2e.py`——真实子进程运行
`westlake sso creds set`（只设 `WESTLAKE_HOME`，不设 `NO_KEYRING`），核对
临时目录落盘、真实钥匙串条目与指针前后一致。

## 实测（端到端）

| 场景 | 结果 |
| --- | --- |
| 钥匙串 → 文件 | 文件写入成功、钥匙串条目已清、读取正常获取学号 |
| 文件 → 钥匙串 | 钥匙串写入成功、明文文件已删、读取正常 |
| 临时 `WESTLAKE_HOME` + 隔离变量 | 只写临时目录文件，真实钥匙串保持「有」 |
| 默认路径 `westlake sso login` | 登录成功（SIS 会话建立） |
| 隔离模式 `status` | 如实显示「keyring：已忽略」，不虚报来源 |

## 历史残留凭据清理

若当前设备存在历史残留的多份凭据，执行一次 `westlake setup` 或 `westlake sso creds set` 重新保存凭据，程序在持久化时会自动清理冗余存储。
