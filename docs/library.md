# 图书馆服务与系统架构指南（library）

> 本文梳理西湖大学图书馆服务系统演进、新版阿法迪云平台（eLibrary）认证与检索协议，以及 CLI 与 API 接入规范。

---

## 1. 系统演进与现状

西湖大学图书馆系统经历了重要迁移：

| 系统平台 | 部署地址 | 当前状态 | 认证机制 | 功能支持 |
| :--- | :--- | :---: | :--- | :--- |
| **老 OPAC 系统** | `172.16.10.223:8180/opac/` | 已整体下线 | 老 CAS 回调（失效） | 已被官方摘除，连根路径均 404 |
| **公网 OPAC 别名** | `opac.westlake.edu.cn` | 静态快照 | 无 | 仅展示静态首页，不反代后端服务 |
| **新版阿法迪云平台** | `mylib.westlake.edu.cn` | **正式运行** | CAS 统一认证 + 长效 userJwt | 书目公开检索、在借图书查询、在线续借 |
| **图书馆座位系统** | `seats.library.westlake.edu.cn` | 独立运行 | 企业微信 JSSDK 签名 | 微信端微应用，暂未开放外部 API |

---

## 2. 新版阿法迪云平台（eLibrary）接入架构

新系统部署于 `https://mylib.westlake.edu.cn/`，核心数据链路如下：

### ① 认证握手与 JWT 跨会话缓存
1. 门户入口：`GET /entrance/myLibEntrance/myLibIndex/MyLibBorrowNow`；
2. 认证跳转：经 `libyyd.westlake.edu.cn` 联动学校 IAM CAS 统一身份认证；
3. 令牌生成：登录成功后下发长效读者身份凭据 `userJwt`（通常多日有效），存储于本地 `~/.westlake_survival/cache/lib/user_jwt.json`；
4. 业务鉴权：后续查询与续借请求携带请求头 `PrimoAuthorization: Bearer <userJwt>`。

### ② 核心服务接口
- **公开书目检索**：`POST /westlakesearch/thirdPart/searchBook`（免鉴权直查题名、作者、索书号与馆藏地）；
- **当前在借图书**：`POST /westlakesearch/thirdPart/getReaderCurrentLoan`（返回书目条码、应还日期、续借次数与馆藏位置）；
- **图书在线续借**：`POST /westlakesearch/thirdPart/renewBook`（传入 `itemBarcode` 完成合规续借）。

---

## 3. 开箱即用命令示例

### 免登录书目检索
```bash
# 检索题名或关键词（返回题名、作者、索书号、馆藏地）
westlake lib search 数据结构
westlake lib search "机器学习" --page 2
```

### 个人借阅查询（需配置校园账号）
```bash
# 列出当前借出图书、应还时间与续借资格
westlake lib loans

# 忽略本地会话缓存强制重新拉取
westlake lib loans --refresh
```

### 在借图书在线续借（受控写操作）
```bash
# 预检续借资格（输出 Action Card 事务预览）
westlake lib renew 12345678 --dry-run

# 凭 Ticket 或 --yes 确认执行
westlake lib renew 12345678 --yes
```

---

## 4. 容错与自愈策略

1. **会话过期自愈**：若服务端返回认证失效（401 / code != 200），客户端自动清空本地 `user_jwt.json` 缓存并透明重新握手；
2. **离线与风控保护**：连续认证失败立即熔断，不反复向统一认证发起暴力试错；
3. **网络要求**：书目检索支持公网访问；借阅查询与续借操作校外访问需连入校园 VPN。
