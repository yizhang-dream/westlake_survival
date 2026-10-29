# 站点与系统

## 全站检索与盘点

```bash
westlake search 关键词            # 官网全站搜索
westlake sites list|site|detail   # 站点与栏目
westlake hosts list               # 全量子站清单
westlake hosts mine               # 常用子站
westlake probe                    # 服务可达性检查
westlake probe scan --full        # 子站在线状态探测
```

## 学生百科 WikiLake

```bash
westlake wiki list                # 条目清单
westlake wiki search 社团         # 站内全文检索
westlake wiki page <条目>         # 读取指定词条
```

## 讲义下载（share，需 [browser] 依赖）

```bash
westlake share add 数据结构 https://...   # 登记一次 OneDrive/SharePoint 分享
westlake share files 数据结构
westlake share download --match 课件
```

链接权限为「组织内任何人可查看」时无需账号即可读取。

## VPN 与诊断

```bash
westlake vpn status               # 深信服 VPN 状态
westlake vpn login                # 登录（验证码在前端页面交互输入）
westlake vpn resources            # 隧道路由
westlake doctor                   # 运行环境完整性检查
westlake find 借书                # 按需求关键词检索对应命令
```

## 凭据

账号凭据由用户在本地网页「设置」页面录入；系统采用钥匙串优先的单一持久化存储机制，终端默认不提示输入明文密码。自动化与隔离测试可指定 `WESTLAKE_HOME` 或设置 `WESTLAKE_NO_KEYRING=1` 开启沙箱模式。设计细节详见 [credential_single_store](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/credential_single_store.md)。
