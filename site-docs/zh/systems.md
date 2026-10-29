# 站点与系统

## 全站检索与盘点

```bash
westlake search 关键词            # 官网全站搜索
westlake sites list|site|detail   # 站点与栏目
westlake hosts list               # 全量子站清单
westlake hosts mine               # 常用子站
westlake probe                    # 服务可达性体检
westlake probe scan --full        # 子站在线普查
```

## 学生百科 WikiLake

```bash
westlake wiki list                # 条目清单
westlake wiki search 社团         # 站内搜索（该站本无搜索）
westlake wiki page <条目>         # 读任意条目
```

## 讲义下载（share，需 [browser] 增强）

```bash
westlake share add 数据结构 https://...   # 登记一次 OneDrive/SharePoint 分享
westlake share files 数据结构
westlake share download --match 课件
```

链接为「组织内任何人可查看」时免账号直读。

## VPN 与诊断

```bash
westlake vpn status               # 深信服 VPN 状态
westlake vpn login                # 登录（验证码在网页前端人工输）
westlake vpn resources            # 隧道路由
westlake doctor                   # 环境九项体检
westlake find 借书                # 不知道命令归哪条就问它
```

## 凭据

网页「设置」页（`westlake` 起服务直达）由本人填写；钥匙串优先、只存一份、终端不问密码。隔离测试用 `WESTLAKE_HOME` 或 `WESTLAKE_NO_KEYRING=1`。设计详见 [credential_single_store](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/credential_single_store.md)。
