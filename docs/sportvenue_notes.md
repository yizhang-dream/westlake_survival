# sportvenue 场馆预约系统侦查笔记（2026-10-27）

游泳的真实入口是**独立的正元智慧场馆系统**：`https://sportvenue.westlake.edu.cn/`。
预约中心（`booking.westlake.edu.cn/yy-sys`）里的「体育场馆」类型与之无关（那里
`state=1`，校验直接回「当前资源类型不可预约」）。本文记录已实测的登录链路与
API 面、以及当前卡住的位置，供后续接入 `sportvenue` 模块使用。

## 系统形态

- 正元智慧集团的多租户产品（`window.g.school=2` 即西湖档位），Vue SPA + 网关代理。
- 代理：业务走 `/site/*`，闸机记录走 `/gate/*`；SSO 登录（`login='1'`，`skipLogin=true`）。
- 场景（scene）列表实测 13 个：J区篮球场、A区足球场、F区匹克球场、会员卡服务、
  C16羽毛球场、C16乒乓球场、C区网球场、J区网球场、C16羽毛球半场-004、cs、
  J1篮球场、J1乒乓球场、J1羽毛球场、健身次卡、**游泳次卡**。
  游泳 scene uuid = `803a9a3e8a0d4e57948903af0841bb56`（用户给的 reserveList 链接即它）。
- 场地下属「场地」：游泳 scene 下只有 `游泳场次`（siteType=DEV，
  uuid `fab6741114a04ca0bf51e9b22afdce4e`，位置 西湖大学/体育中心/游泳馆/游泳，
  kindName 游泳馆，supportPeriod=N）。

## 登录链路（requests 可全自动，2026-10-27 实测通）

1. `GET /site/cas/address?redirectUrl=<当前URL>&queryParam=<base64(当前URL)>`
   → 返回 `https://sportvenue.westlake.edu.cn/authcenter/toLoginPage?...`。
   **所有请求都要带签名参数**（见下）。
2. GET 该页 → 302 到 `iam.westlake.edu.cn/cas/oauth2.0/authorize?client_id=tycgyy&...`
   → 302 `/idp/authCenter/authenticate` → 302 `/ac/#/index?lck=…&entityId=tycgyy`。
   走 `iam` 模块的认证链（queryAuthMethods → verifyCodeIsNeed → getJsPublicKey →
   authExecute → authnEngine），拿到 `locationValue`
   = `sportvenue.westlake.edu.cn/authcenter/doOauth2?code=…`。
3. GET doOauth2（301/302 一跳）→ `302 index.html#/blank?uniToken=<JWT>`。
   从 Location 里正则抠 `uniToken`（requests 看得到，因为是 302 的 Location）。
4. `POST /site/cas/token {"platForm":"CAS","client":"PC","token":<uniToken>}`
   → `{token, refreshToken, uuid:学号}`。之后所有请求带头 `token: <token>`。
5. `GET /site/system/login/getLoginUser` 验活，返回学号/姓名/手机/身份。

### 签名（每个请求的 query 都要拼）

`getSign()`：`appId=1497016617475903488`（定值）、`nonce`=32 位随机串
（字符表 `ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz0123456789`）、
`timeStamp`=毫秒；`key` 由混淆的 `getKeys()` 拼出，实测为
`57325972627c40bd8c7729693d293705`；
`sign = md5("appId=…&nonce=…&timeStamp=…&key=…")`。

## API 面（与预约直接相关的）

- 场景：`GET /site/api/site/scene/list`、`GET /site/api/site/scene/detail?uuid=…`
- 场地列表：`POST /site/api/reserve/current/page`
  `{sceneUuid, reserveDate:"YYYY-MM-DD", pageNum, pageSize, resvKind:"CURRENT_RESERVE"}`
- 逐日可约状态：`POST /site/api/reserve/cross/detail`
  `{siteUuid, siteType, reserveStartDate, reserveEndDate}` →
  `groupReserveVos[].reserveStatus{reserveStatus Y/N, reserveStatusReason}`、
  `feeRuleVo`（计费）、`reserveRule`（提前天数等）
- 我的预约：`POST /site/api/reserve/current/page`（同上）、取消 `/api/reserve/cancelReserve`
- 下单：`/api/reserve/addReserve`（带 `purchaseTicketInfos`：`payableAmount/
  chargingUnitPrice/feeRelatedValue/ticketCount`）→ `/api/resv/trade/place/order`
  → `/api/resv/trade/pay/type`（线上/线下/次卡 PAY_CARD）
- 次卡：`/api/cup/card/list|kind|own|purchase|use/rec|session/price`
  （购买次卡即游泳缴费形态之一；`supportCard` 的场次可用次卡支付）

## 当前卡点（2026-10-27 实测）

游泳、C区网球场、C16羽毛球场的每一天（连续 31 天）`reserveStatus` 全是 `N`，
原因都是 **"表单规则未找到！！！"（code 40100082）**，
`feeRuleVo=null`、`reserveRule=null`。即：系统在线、登录正常、场地数据在，
但**预约表单规则没有配置（或本账号身份没有匹配的表单）**，任何人都点不进下单页。
两种可能：管理端还没把表单/计费配齐；或者表单按身份（教职工/学生）分发，
学生身份没有配。下一步：用户在 i西湖/浏览器里以本人身份打开同一路径看是否
同样「不可预约」；若同样，则找体育中心/总务部确认开放时间。

## 复用入口

侦查脚本模式见本仓 git 历史（2026-10-27 会话），登录四步 + 签名函数可直接
搬进将来的 `sportvenue` 模块；token 存内存不落盘。
