# 图书馆系统迁移（2026-10-28 实测）

用户反馈「没开梯子，图书馆页面显示不了」。实测结论：**与代理/VPN 无关**，是学校把图书馆系统整体换掉了，工具还在打老接口。

## 现场

| 探测 | 结果 |
| --- | --- |
| `GET http://172.16.10.223:8180/` | **302 → `/page/login.jsp`** |
| `GET http://172.16.10.223:8180/page/login.jsp` | 200，标题「阿法迪云智能图书管理平台 eLibrary System」，表单字段 `account` / `password`，页面无 CAS/SSO 字样 |
| `GET http://172.16.10.223:8180/opac/` | **404**（连上下文根都没了） |
| `GET /opac/booklist.jsp`（检索） | 404 |
| `GET /opac/newbooklist.jsp?target=2`（新书） | 404 |
| `GET /opac/cas/casLogin.do`（借阅 CAS 回调） | 404 |
| `GET http://opac.westlake.edu.cn/` | 200，但正文开头是 `<!-- saved from url=(0031)http://172.16.10.223:8180/opac/ -->`——**首页静态快照** |
| `GET http://opac.westlake.edu.cn/opac/*` | nginx 404 |
| `GET http://opac.westlake.edu.cn/page/login.jsp` | 404（公网别名**不反代**新平台） |
| `https://opac.westlake.edu.cn/` | 连接失败 |
| `POST https://catalog.lib.westlake.edu.cn/headless/bolan-newbook/api/newbook/tenantRule` | 401 `{"code":"UNAUTHORIZED","message":"需要先登录"}` |
| `POST https://catalog.lib.westlake.edu.cn/headless/bolan-search/api/search/book` | 401 同上 |

本机默认路由走 `10.16.127.254`（接口地址 `10.16.122.222`），即当前在校园网内，所以内网 IP `172.16.10.223` 可直连——**不需要任何梯子/VPN**，页面本身也一直返回 200，只是三块数据全空。

## 为什么页面显示不出来

页面返回 200，但三块数据各自失败：

1. **检索**：打 `booklist.jsp` → 404；
2. **新书**：打 `newbooklist.jsp?target=2` → 404；
3. **借阅**：走 CAS 回调 `casLogin.do` → 失效（报「CAS 登录返回未预期的状态码 401」）。

旧文案统一写成「需校园网/VPN」，但真实原因不是网络：是**服务端换了系统**。更麻烦的是借阅那条——每次渲染页面都会尝试一次 CAS 登录，对一个已失效的回调反复登录有锁号风险。

## 这次改了什么

- `lib/opac.py` 新增 `detect_backend()`：探一次老 OPAC `/opac/` 是否还在、新平台 `/page/login.jsp` 是否在线（结果缓存 10 分钟），模块文档记录本次实测。
- CLI：`westlake lib search` / `lib loans` 先过 `_lib_backend_guard()`，打印同一段说明并退出 1，**不再发起 CAS 登录**。
- `tools/module_smoke.py`：新增 `MIGRATED` 状态（输出含「系统已迁移」），不算 FAIL，不列入「需要处理」。
- **2026-10-28 晚按用户要求下线 WebUI 的「图书馆」页**（本人在新平台登录未成功，功能短期无望）：删除 `/lib` 路由、`lib.html` 模板、导航项与 `capabilities.py` 的页面清单条目。页面上线过的那版（迁移说明 + 三块「暂不可用」）已随删除一并退役；`lib/opac.py` 与 `westlake lib` 两条 CLI 保留，等接上新平台可直接复用。

## 要真正接上新平台，还缺什么

- 新平台是**平台自有账号**（`account` + `password` 表单），是否等于统一身份认证密码未知——**不能用猜的**，反复试真实账号有锁号风险；
- 需要在浏览器里由本人登录一次，再抓 `/page/` 下的真实接口（检索、读者借阅、续借），确认分页与字段；
- 公网别名不反代 `/page/`，所以校外仍要 VPN；校园网内直连可用。

在此之前，查书与借阅请直接访问图书馆网站；工具侧保持「说清楚现状、不误报、不锁号」。

## 验收（端到端）

| 链路 | 输入 | 结果 |
| --- | --- | --- |
| 页面 | `GET http://127.0.0.1:2018/lib`（真启服务） | 200，含「图书馆系统已迁移」与三处「暂不可用」，0.1s 内返回，无 AuthError/ParseError |
| 检测 | `detect_backend(force=True)` | `{"opac_alive": False, "new_platform": True, "detail": "老 OPAC /opac/ → HTTP 404；新平台 /page/login.jsp → HTTP 200（eLibrary）"}` |
| CLI | `westlake lib loans` / `westlake lib search 数据结构` | 打印迁移说明，退出 1，不发 CAS 登录 |
| 冒烟 | `python tools/module_smoke.py lib` | `MIGRATED 2`，不再计入 FAIL |
