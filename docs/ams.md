# 教学系统接入（`ams.westlake.edu.cn`，2026-10-28）

## 这是什么

`ams.westlake.edu.cn` 是**西湖大学教学系统**（不是图书馆）。实测形态：

- 前端 Vue SPA 在 `/home/`，标题「西湖大学教学系统」；后端网关 `/portal-service/api/v1/…`；
- 首页显示学期、教学周、当日日程、快捷服务；菜单里有**学籍信息 / 学生信息核对 / 学生选择导师 / 选课 / 我的课表 / 实验实习实践**；
- 解析到内网 `172.16.10.195`，与资源门户同机；校外需 VPN。

## 登录：走 IAM 统一认证（不用另设密码）

```
GET https://ams.westlake.edu.cn/            → 302 /login
GET https://ams.westlake.edu.cn/login       → 302 /sso/login  (refer=…)
GET https://ams.westlake.edu.cn/sso/login   → 302 iam.westlake.edu.cn/ac/#/index?lck=context_CAS_…
                                                 &entityId=https://ams.westlake.edu.cn
```

即 IAM 的 CAS 上下文，与 SIS 同一套统一身份认证密码。**经典 CAS 不接这个 service**：
`sso.westlake.edu.cn/cas/login?service=https://ams.westlake.edu.cn/sso/login` 返回
`Application Not Authorized`，所以必须走 `iam.login_for()`（`/idp/authn/*` 那条路），
不能套 Canvas 的 `CASAuthorizer`。

会话：登录成功后只拿到 `ams.westlake.edu.cn` 的 `SESSION` cookie（以及 `iam` 的 `usk`）。
缓存到 `~/.westlake_survival/ams_cookies.json`（0600，遵循 `WESTLAKE_HOME` 重定位），
8 小时有效；每次先用 `/portal-service/api/v1/home/index` 验活，失效才重新登录——
避免每次都去 IAM 过一遍密码（验证码风控与锁号风险）。

## 已接的只读接口

| 能力 | 接口 | 说明 |
| --- | --- | --- |
| 学期 / 教学周 | `GET /portal-service/api/v1/home/index?identity=STUDENT` | 学期名、周次、是否在教学周 |
| 课程日程 | `GET /portal-service/api/v1/schedule/get-calendars?startDateStr=&endDateStr=&reqType=Date` | 按日返回 `calendarList`：课名 / 起止时间 / 地点；重复行按「日期+时段+课名+地点」去重 |
| 服务入口 | `GET /portal-service/api/v1/common/home/get-all-menus?identity=STUDENT` | 菜单树，`href` 指向学籍/选课/课表等子系统 |
| 通知 | `GET /portal-service/api/v1/notice-view/get-all-notice` | 未读 + 全部 |

响应统一 `{"code":0,"msg":"操作成功","data":…}`；非 0 视为业务失败。

## 入口

```bash
westlake ams status          # 学期/周次 + 今天的课
westlake ams today           # 今天的课
westlake ams schedule        # 本周课程（--start/--end 指定区间，--json 出结构化）
westlake ams menus           # 学籍 / 导师 / 选课 / 我的课表 入口链接
westlake ams notices         # 通知
westlake ams login           # 强制重登（缓存会话失效时）
```

WebUI：导航「教学」→ `/ams`，一页给出学期周次、今天与本周课程、服务入口、通知；
页面层 2 分钟磁盘缓存，模块层 8 小时会话缓存。

## 边界

- **只读**：本模块只取课表/周次/菜单/通知。选课、学籍修改等写操作一律不做，页面上给的是跳转到系统的链接。
- 未接：成绩、考试、选课余量（都在 `/student/for-std/*` 子系统里，需要各自探接口）。
- 个人数据：课表与姓名属个人信息，输出到第三方前应脱敏；本仓库文档不记录任何人的真实课表。

## 验收（端到端，2026-10-28）

| 链路 | 输入 | 结果 |
| --- | --- | --- |
| 模块 | `ams.overview()` / `ams.this_week()` / `ams.menus()` | 0.6s 首次（含 IAM 登录），之后 0.1s（命中缓存）；本周 14 条课程（去重后）、菜单 5 个可跳转入口 |
| CLI | `westlake ams status`、`ams menus`、`ams schedule --json` | 输出学期第 9 周、当天 1 节课、表格与 JSON 正常 |
| 页面 | 真启服务 `GET /ams` | 200，0.3s（缓存），含「教学周 / 今日课程 / 本周课程 / 服务入口」与课程标题 |
| 全站 | `python tools/webui_smoke.py` | 32 页 0 失败（新增 `/ams`） |
| 路由 | `westlake find 课表` | 命中 `westlake ams` |
