# 西湖大学自助文印（PMS）API 端点清单

> 目标系统：图书馆自助文印控制器（联创 UniOpm「云打印」）
> `http://print.lib.westlake.edu.cn:9130`（172.16.10.222）
> 探测日期：**2026-09-22**（校园网内实测）
> 对应实现：`src/westlake_survival/pms/client.py`

本文档是「人读版」端点清单：**文档原文给出的端点 → 实际可路由路径 → 参数 →
响应字段 → 本库实现状态**，与 `client.py` 的方法一一对应。

---

## 1. 文档页与抓取记录

| 项目 | 结论 |
| --- | --- |
| 入口 | `GET /api.html` → **HTTP 200**（517 字节） |
| 本质 | **JS 壳**：页内 `$.ajax({url: "/api/system/Help/Get"})`，把返回的 HTML 塞进 `#Help` |
| 真正的文档 | `GET /api/system/Help/Get` → **HTTP 200**，`text/html`，**369,060 字节**（≈360 KB） |
| 文档规模 | **4 个模块 / 32 个控制器 / 711 个动作**（按 `模块: X / 控制器: X / 动作: X` 标签统计，重载动作按文档原样计数） |
| 路由前缀 | 前端 `client/new/*/js/host.js`：`var host = "/api"` |

因此**只抓 `api.html` 拿不到端点**，必须先请求 `api/system/Help/Get`。

### 1.1 URL 里的控制器名是「短名」（关键坑位）

文档里写的相对路径带**全限定控制器名**，例如：

```
文档:  api/client/server.controller.client.PrintJobController/Get
实际:  /api/client/PrintJob/Get          ← 去掉命名空间，只留 <Name>Controller 的 <Name>
```

对照前端实测：`/api/client/Auth/Check`、`/api/client/Paper/GetPaper`、
`/api/client/PrintJob/Get`、`/api/client/Scan/Get`、`/api/client/Report/Stat`、
`/api/client/CloudPrint/Upload`、`/api/client/Station/GetList`、
`/api/client/FeeStd/Get`、`/api/client/Pay/GetBill`、`/api/system/MulLan/Get`。
按文档里的长名请求会返回 `{"Message":"No HTTP resource was found ..."}`（HTTP 404）。

### 1.2 统一响应信封

所有 `/api/**` 业务接口返回同一个信封（实测）：

```json
{ "code": 0, "message": "", "result": null }
```

| code | 含义 | 本库映射 |
| --- | --- | --- |
| `0` | 成功，数据在 `result` | 正常返回 |
| `4` | **无效会话，未登录**（实测：匿名请求任意需登录接口） | `SessionExpired` |
| 其它非 0 | 业务拒绝，原因在 `message` | `ActionError`；登录流程归一为 `InvalidCredentials` |

> 服务端**没有**公开错误码枚举表（文档页与前端 JS 均未列出），故除 `0` / `4`
> 之外只能按 `message` 透传。`code == 4` 的语义来自前端
> `common.js` 的 `returnAjax()`：`data.code == 4` 即视为「未登录/会话失效」。

登录成功/失败的具体 code 值**未验证**（无真实账号，禁止发凭据），
本库按「登录非 0 即凭据问题」归一处理，见 `client.py::PMSClient.login`。

---

## 2. 认证流程（对照前端 `client/new/cprintMobile/js/login.js`）

```
① GET  /api/client/Auth/PublicKey          → result = {publicKey, nonceStr}
② POST /api/client/Auth/GetAuthToken       → 顶层 szToken（注意不在 result 里）
③ POST /api/client/Auth/Login              body = {szLogonName, szPassword, szToken}
                                            szPassword = RSA_PKCS1v15(password + ";" + nonceStr)
                                            Content-Type: application/json
④ 之后所有请求靠 Cookie 会话；POST /api/client/Auth/Check 校验（code==0 表示仍登录）
⑤ GET  /api/client/Auth/Logout             退出
```

- 公钥是 **X.509 SubjectPublicKeyInfo**（base64），前端用 `JSEncrypt` 加密，
  等价于 **RSAES-PKCS1-v1_5**。本库用纯标准库实现（`rsa_public_numbers` /
  `encrypt_password`），零新增依赖。
  实测该公钥为 **128 字节模长、e = 3**（不是常见的 65537）。
- 实测 `GET /api/client/Auth/GetAuthToken`（匿名）返回：
  `{"szAuthType":"password","szInfo":null,"szToken":"<32位hex>","szStaSessionId":null,"code":0,"message":"","result":null}`
- 用户名/密码来源：`PMSClient(username=..., password=...)` 优先；否则
  `westlake_survival.sso.read_credentials()`（返回 `(sid, password)`，无凭据抛 `AuthError`）。
  解析逻辑见 `client.py::PMSClient.resolve_credentials`（公开方法，便于调用方提前校验凭据）。
  `westlake_survival.sso` 导入失败时会降级为**延迟导入**，只在真正需要凭据时报错。

---

## 3. 已实现端点（与 `client.py` 一一对应）

`<base>` = `PMS_BASE` = `http://print.lib.westlake.edu.cn:9130`（可用环境变量
`WESTLAKE_PMS_BASE` 覆盖）。

### 3.1 AuthController → `/api/client/Auth/*`

| 本库方法 | 文档动作（相对路径） | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `public_key()` | `...AuthController/PublicKey` | GET/POST | `/api/client/Auth/PublicKey` | — | `result.publicKey`(RSA SPKI b64), `result.nonceStr` | ✅ 匿名实测 200 |
| `auth_token()` | `...AuthController/GetAuthToken` | GET/POST | `/api/client/Auth/GetAuthToken` | — | 顶层 `szToken`,`szAuthType`,`szInfo`,`szStaSessionId` | ✅ 匿名实测 200 |
| `login()` | `...AuthController/Login` | POST | `/api/client/Auth/Login` | body `{szLogonName, szPassword, szToken}` | `result` = 用户信息（`UNIACCOUNT`） | ⚠️ 路由实测存在（空 body 报错），成功响应未验证（无账号） |
| `check()` | `...AuthController/Check` | GET/POST | `/api/client/Auth/Check` | — | `code`,`message`,`result`(用户信息),`SessionId` | ⚠️ 匿名返回 `code=4` |
| `ensure_logged_in()` | （Check + Login 组合） | — | — | — | — | — |
| `logout()` | `...AuthController/Logout` | GET/POST | `/api/client/Auth/Logout` | — | `code`,`result`(回跳地址) | ⚠️ 路由按同构短名，未验证 |
| `user_info()` | `...AuthController/GetUserInfo` | GET/POST | `/api/client/Auth/GetUserInfo` | `szLogonName`(可选) | `result` = 用户信息（原始 dict） | ⚠️ 匿名 `code=4` |
| `change_password()` | `...AuthController/ChgPassword` | POST | `/api/client/Auth/ChgPassword` | body `ChgPasswordReq`（字段名**文档未给**，按 `szLogonName/szOldPassword/szNewPassword` 推断） | `BaseResponse` | ⚠️ 字段推断，未验证 |

前端实际读取的用户字段：`szTrueName`（姓名）、`dwSex`（0 女 / 1 男）、
`szLogonName`、`szEmail`、`szTel`。**未发现独立的「余额」接口**；
余额相关数据在 `Report/Stat` 与 `Report/DetailPage` 的金额字段里
（单位：**分**）。

### 3.2 StationController → `/api/client/Station/*`

| 本库方法 | 文档动作 | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `list_stations()` | `...StationController/GetList` | GET | `/api/client/Station/GetList` | — | 见 §4.1 `Station` | ✅ 匿名实测 200，返回 4 台 |
| `list_servers()` | `...StationController/GetSrvList` | GET | `/api/client/Station/GetSrvList` | — | `dwSN,szName,szIP,szMemo` | ✅ 匿名实测 200 |
| `get_station(dev_sn)` | `...StationController/GetByDevSN` | GET | `/api/client/Station/GetByDevSN` | `dwDevSN` | 单个 `Station` | ⚠️ 匿名 `code=4` |

实测 `GetList` 结果（2026-09-22）：`dwDevSN` 1001 / 1002 / 1003 / 1004，
名称「云栖图书馆彩色」「云栖图书馆黑白」「云谷图书馆黑白」「云谷图书馆彩色」。

### 3.3 PaperController → `/api/client/Paper/*`

| 本库方法 | 文档动作 | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `list_papers()` | `...PaperController/GetPaper` | POST/GET | `/api/client/Paper/GetPaper` | — | 见 §4.2 `Paper` | ✅ 匿名实测 200，返回 A3/A4/A0/A1 |

### 3.4 PrintJobController → `/api/client/PrintJob/*` 与 `/api/client/CloudPrint/*`

| 本库方法 | 文档动作 | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `list_print_jobs()` | `...PrintJobController/Get` | GET/POST | `/api/client/PrintJob/Get` | — | `result` = `PrintJob[]` | ⚠️ 匿名 `code=4`；字段取自前端解析 |
| `list_print_jobs(dev_sn=)` | `...PrintJobController/GetByDevSN` | GET | `/api/client/PrintJob/GetByDevSN` | `dwDevSN` | 单个任务 | ⚠️ 未验证 |
| `upload(...)` | `...CloudPrintController/Upload` | POST | `/api/client/CloudPrint/Upload` | **multipart**：`szPath`(file),`dwPaperId`,`dwDuplex`,`dwColor`,`dwFrom`,`dwTo`,`dwCopies`,`dwPdfImage`,`BackURL` | `code`/`message` | ✅ 字段取自前端 `cprint.html` 表单；⚠️ 成功响应未验证 |
| `create_print_job(req)` | `...PrintJobController/Create` | POST | `/api/client/PrintJob/Create` | body `CreatePrintJobReq`（**文档只给类型名，未给字段**） | `BaseResponse` | ⚠️ 透传，未验证 |
| `set_print_job(**f)` | `...PrintJobController/Set` | POST | `/api/client/PrintJob/Set` | body `SetPrintJobReq`（**字段未给**，参照 `dwJobId/dwCopies/dwDuplex/dwColor`） | `BaseResponse` | ⚠️ 透传，未验证 |
| `delete_print_job(id, old)` | `...PrintJobController/Del` | POST | `/api/client/PrintJob/Del` | body `{dwJobId, dwOldJobId}`（前端实测） | `BaseResponse` | ✅ 字段取自前端 `printDoc.js`；⚠️ 未验证 |
| `preview_page(id, ct, page)` | `...PrintJobController/PreviewPage` | GET | `/api/client/PrintJob/PreviewPage` | `dwJobId`,`dwCreateTime`,`pageNo` | `result` = PNG 的 base64 字符串 | ⚠️ 未验证 |
| `take_out(id, old)` | `...PrintJobController/TakeOut` | GET | `/api/client/PrintJob/TakeOut` | `dwJobId`,`dwOldJobId` | `TakeOutResponse` | ⚠️ 需设备会话 |
| `fee_standards(sn)` | `...PrintJobController/GetCurrentUserFeeStd` | GET | `/api/client/PrintJob/GetCurrentUserFeeStd` | `dwFeeItemSN`(可选) | `OPMFEESTD[]` | ⚠️ 匿名 `code=4` |

> **建任务的两条路径**：文档同时给了 `PrintJob/Create`（JSON `CreatePrintJobReq`）
> 和 `CloudPrint/Upload`（multipart）。前端「云打印」**只用后者**——
> 一次 multipart 上传即完成建任务，字段名已在 §3.4 列出。本库以
> `upload()` 为主入口，`create_print_job()` 保留为低层透传。

### 3.5 ScanController → `/api/client/Scan/*`

| 本库方法 | 文档动作 | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `list_scan_jobs()` | `...ScanController/Get` | GET/POST | `/api/client/Scan/Get` | — | `result` = `ScanJob[]` | ⚠️ 匿名 `code=4`；字段取自前端模板 |
| `set_scan_job(**f)` | `...ScanController/Set` | GET/POST | `/api/client/Scan/Set` | body `SetScanReq`（**字段未给**） | `BaseResponse` | ⚠️ 透传，未验证 |
| `delete_scan_job(id)` | `...ScanController/Del` | POST | `/api/client/Scan/Del` | body `DelScanReq`（**字段未给**，按 `{dwJobId}` 假设） | `BaseResponse` | ⚠️ 假设同构，未验证 |
| `download_scan(id, dest, additional=)` | `...ScanController/Download` | GET/POST | `/api/client/Scan/Download` | `dwJobId`,`dwAdditional`(前端传 `dwSubmitTime`) | 二进制流（`HttpResponseMessage`） | ✅ 参数取自前端 `scanDoc.html` 下载链接；⚠️ 未验证 |

### 3.6 ReportController → `/api/client/Report/*`

| 本库方法 | 文档动作 | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `usage_stat(begin, end)` | `...ReportController/Stat` | POST | `/api/client/Report/Stat` | body `{dwBeginDate, dwEndDate}`（前端实测） | `result` = `UsageSummary[]`：`dwType,dwUseTimes,dwPages,dwUsedCardMoney,dwUsedFreeMoney,dwUsedMoney` | ✅ 请求字段取自前端 `entry.js`；⚠️ 匿名 `code=4` |
| `usage_records(...)` | `...ReportController/DetailPage` | POST | `/api/client/Report/DetailPage` | body `{dwBeginDate,dwEndDate,dwType,dwPageNo,dwRowCount}`（前端实测） | `dwTotalPage` + `result` = `UsageRecord[]` | ✅ 请求字段取自前端 `footprint.js`；⚠️ 匿名 `code=4` |
| `usage_detail(req)` | `...ReportController/Detail` | POST | `/api/client/Report/Detail` | body `ReportDetailReq`（**字段未给**） | `BaseResponse` | ⚠️ 透传 |
| `invoice_page(req)` | `...ReportController/InvoicePage` | POST | `/api/client/Report/InvoicePage` | body `ReportDetailPageReq` | `DetailPageResponse` | ⚠️ 透传 |
| `make_invoice(req)` | `...ReportController/DoInvoice` | POST | `/api/client/Report/DoInvoice` | body `InvoiceDoReq`（**字段未给**） | `BaseResponse` | ⚠️ 透传 |

`UsageRecord` 各字段与前端「足迹」页的对应关系见 §4.4。

### 3.7 FeeStdController / PayController → `/api/client/FeeStd/*`、`/api/client/Pay/*`

| 本库方法 | 文档动作 | HTTP | 实际路径 | 参数 | 响应字段 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| `fee_standard(req)` | `...FeeStdController/Get` | POST | `/api/client/FeeStd/Get` | body `FeeStdReq`（**字段未给**） | `BaseResponse` | ⚠️ 匿名 `code=4` |
| `get_bill(req, **q)` | `...PayController/GetBill` | POST/GET | `/api/client/Pay/GetBill` | body `GetBillReq`（**字段未给**）+ 查询串 `dwCardPay,szExtInfo` | `GetBillResponse` | ⚠️ 匿名 `code=4` |
| `pay_result(**q)` | `...PayController/GetPayResult` | POST/GET | `/api/client/Pay/GetPayResult` | — | `BaseResponse` | ⚠️ 未验证 |
| `wait_pay_result(**q)` | `...PayController/WaitPayResult` | POST/GET | `/api/client/Pay/WaitPayResult` | — | `BaseResponse` | ⚠️ 未验证 |
| `recharge(...)` | `...PayController/Recharge` | POST/GET | `/api/client/Pay/Recharge` | 查询串 `szType,dwFee,state[,szOperator,szMemo]` | `BaseResponse` | ⚠️ **会真实动一卡通余额** |

---

## 4. 数据模型字段表（`models.py`）

字段名一律使用**服务端原始名**（括号内为本库的 dataclass 字段名），
`from_json` 对缺字段/None/脏类型全部容错。

### 4.1 `Station`（来源 `Station/GetList` / `GetByDevSN`）

实测样例（截断）：

```json
{"dwDevSN":1001,"dwFunction":7,"dwCtrlType":1,"dwProperty":95,"dwStatus":1,"dwKind":0,
 "dwTrayPaper1":9,"dwTrayPaper2":8,"dwTrayPaper3":0,"dwTrayPaper4":0,"dwModel":102,
 "dwSpeed":0,"dwOpenTime":0,"dwCloseTime":1439,"dwChgTime":1789960325,"dwUpdateTime":1790014224,
 "szName":"云栖图书馆彩色","szIP":"172.16.53.220","szPosition":"","szTel":"","szCardIP":"",
 "szMAC":"68eda43bb69e","szCampus":"","szRoomName":"","szDeptName":"",
 "szPrtDriver":"FX DocuCentre-V C2265 PCL 6","szStatInfo":"系统空闲","szMemo":""}
```

| 原始字段 | 本库字段 | 说明 |
| --- | --- | --- |
| `dwDevSN` | `dev_sn` | 设备号（= 网点 id） |
| `szName` | `name` | 网点名 |
| `szIP` / `szCardIP` / `szMAC` | `ip` / `card_ip` / `mac` | 网络信息 |
| `dwStatus` | `status` | **位图**：`1`=空闲，`2`=忙碌，`0`=未开放，`0x20/0x200/0x400/0x800/0x1000/0x2000/0x10000`=不可用（故障/告警/通信失败等）。属性 `is_idle` / `is_busy` / `is_disabled` |
| `szStatInfo` | `status_text` | 人类可读状态，例「系统空闲」「A4纸已快用完」 |
| `dwProperty` | `capabilities` | **位图**：`1`=打印，`2`=复印，`4`=扫描，`8`=彩色。属性 `supports_print` / `supports_copy` / `supports_scan` / `supports_color`（字段名不用 `property`，避免遮蔽内置） |
| `dwTrayPaper1..4` | `trays` | 各纸盒纸型 id（`8`=A3, `9`=A4, `0`=空）；属性 `papers` → `["A3","A4"]` |
| `dwFunction`/`dwCtrlType`/`dwKind`/`dwModel`/`dwSpeed` | `function`/`ctrl_type`/`model`(+`raw`) | 暂只透传，未翻译 |
| `szCampus`/`szRoomName`/`szDeptName`/`szPosition` | `campus`/`room_name`/`dept_name`/`position` | 实测多为空串 |
| `szPrtDriver` | `printer_driver` | 驱动名 |
| `dwOpenTime`/`dwCloseTime` | `open_time`/`close_time` | 当日分钟数（实测 `0`/`1439` = 全天） |
| `dwChgTime`/`dwUpdateTime` | `changed_at`/`updated_at` | **Unix 秒**，转 aware datetime |
| `szMemo`/`szTel` | `memo`/`tel` | — |
| （全部） | `raw` | 原始 dict 备份，便于取未映射字段 |

### 4.2 `Paper`（来源 `Paper/GetPaper`）

实测样例：`{"dwPaperID":9,"dwWidth":21000,"dwHeight":29700,"dwStatus":1,"dwTrayIndex":0,"szPaperName":"A4"}`

| 原始字段 | 本库字段 | 说明 |
| --- | --- | --- |
| `dwPaperID` | `id` | 纸型 id（A3=8, A4=9, A0=123, A1=124） |
| `szPaperName` | `name` | 纸型名 |
| `dwWidth`/`dwHeight` | `width_mm`/`height_mm` | 服务端单位 **0.01mm**（A4=`21000`×`29700` → 210×297mm），本库除以 100 换算为 mm |
| `dwStatus`/`dwTrayIndex` | `status`/`tray_index` | — |

### 4.3 `PrintJob`（来源 `PrintJob/Get`）与 `ScanJob`（来源 `Scan/Get`）

`PrintJob` 字段取自前端 `printDoc.js` 的解析逻辑（响应样本**无账号无法实测**）：

| 原始字段 | 本库字段 | 说明 |
| --- | --- | --- |
| `dwJobId` | `id` | 任务号 |
| `szJobName` | `name` | 文件名 |
| `dwCreateDate` / `dwCreateTime` | `created_date` / `created_time` | `YYYYMMDD` / `HHMMSS` 打包整数；`created_at` 属性拼成 datetime（例 `20260922`+`100000` → 2026-09-22 10:00:00） |
| `szPaperDetail` | `paper_detail` | **是一段 JSON 字符串**，形如 `[{"dwPaperID":9,"dwBWPages":2,"dwColorPages":0}]`；本库反序列化为 `list[dict]`，属性 `total_pages` 求和 |
| `szAttribe` | `attribute` | 含 `single`（单面）/`vdup`（双面长边）/`color`（彩色）关键字；属性 `duplex` / `is_color` |
| `dwCopies` | `copies` | 份数 |
| `dwDevSN` | `dev_sn` | 目标网点 |
| `dwStatus`/`szStatus`/`dwPages`/`dwPrintedPage` | `status`/`status_text`/`pages`/`printed_page` | 容错读取（字段可能缺失） |
| （全部） | `raw` | 原始 dict |

`ScanJob` 字段取自前端 `scanDoc.html` 模板：

| 原始字段 | 本库字段 | 说明 |
| --- | --- | --- |
| `dwJobId` | `id` | 任务号 |
| `szDisplayName` | `display_name` | 展示名（前端「文件大小/名称」处用） |
| `szFileName` | `file_name` | 回退取 `szDisplayName` |
| `dwFileSize` | `file_size` | 字节（前端换算 B/KB/MB） |
| `dwSubmitDate` / `dwSubmitTime` | `submit_date`/`submit_time` | 同上打包口径；`submitted_at` 属性 |
| `dwStatus` | `status` | 位图，前端用 `dwStatus & 256` 判定「可下载」 |
| （全部） | `raw` | 原始 dict |

### 4.4 `UsageRecord`（来源 `Report/DetailPage`）与 `UsageSummary`（来源 `Report/Stat`）

前端「足迹」页只用了下面这些字段（金额单位均为**分**）：

| 原始字段 | 本库字段 | 说明 |
| --- | --- | --- |
| `dwDate` / `dwTime` | `date` / `time` | `YYYYMMDD` / `HHMMSS`；`time_at` 属性拼 datetime |
| `dwType` | `type` | 类别（前端切页签时下发 1/2/3，语义为打印/复印/扫描） |
| `dwPages` | `pages` | 数量（前端标签「数量」） |
| `dwCopies` | `copies` | 份数（若有） |
| `dwPaperID` | `paper_id` | `8`=A3 / `9`=A4；属性 `paper` |
| `dwUsedCardMoney` | `card_money` | 卡消费（分） |
| `dwUsedFreeMoney` | `free_money` | 补助（分） |
| `dwUsedMoney` | `local_money` | 本地消费（分） |
| `dwSettleType` | `settle_type` | `& 0xff == 4` 判定「手工收费」，否则「自助收费」 |
| `dwJobId` | `job_id` | 关联任务 |
| `szJobName`/`szName` | `name` | 名称（若有） |
| （全部） | `raw` | 原始 dict |
| — | `cost` / `cost_yuan` | 属性：`(card+free+local)/100`，单位元 |

`Report/DetailPage` 顶层：`dwTotalPage`（→ `UsagePage.total_page`）、
`dwTotalCount`/`dwTotalRows`（→ `total_count`，存在才取）、`result`（记录数组）。

`UsageSummary`：`dwType, dwUseTimes, dwPages, dwUsedCardMoney, dwUsedFreeMoney, dwUsedMoney`
（前端首页把 `dwUseTimes` 求和显示「累计次数」，把三种金额求和/100 显示「累计消费」）；属性 `cost` 同口径。

---

## 5. 已文档但**未实现**的端点（及原因）

| 模块 | 控制器 | 动作数 | 为什么没实现 |
| --- | --- | --- | --- |
| `client` | `AuthController` | 74 | 已实现核心 8 个；其余为扫码登录（`QrLogin`/`QR`/`QrImg`/`LoginQRSetInterval`）、第三方 SSO 跳转（`SSOLogin*`/`SSOPage`/`SSOMobile`/`UniLogin`/`UniOAuth`/`UniEntry`/`ZHLibEntry`/`ThirdPage`）、一卡通绑卡（`Card`）、注册（`Register`）。均为浏览器跳转/设备扫码场景，非 API 库职责 |
| `client` | `CloudPrintController` | 27 | 只实现了 `Upload`；`UrlPrint`/`LocalPrint`/`ExtPrint`（按 URL/本地路径云打印）、`UploadImage` 未实现 |
| `client` | `PrintJobController` | 26 | 未实现 `Upload`/`UploadPreview`（需配合 `Create` 两段式）、`TakeOutAuth`/`TakeOut_bak`/`TakeOutError`（网点终端会话）、`OPM*`/`Where`（OPM 内部/查询 DSL） |
| `client` | `ScanController` | 22 | 已实现 Get/Set/Del/Download；`Where` 未实现 |
| `client` | `ReportController` | 18 | 已实现 5 个；`CurrentUserPutToClient` 等框架内部动作未实现 |
| `client` | `PayController` | 32 | 只封装了 `GetBill`/`GetPayResult`/`WaitPayResult`/`Recharge`；`PayQR`/`QR`/`QrImg`（二维码支付流）、`CardPay`、`GetPrintPayInfo` 未实现 |
| `client` | `PaperController`/`FeeStdController`/`StationController` | 15/14/15 | 只实现取数动作；`Where`（条件 DSL）等未实现 |
| `selfservice` | 全部 8 个控制器 | 233 | 面向**网点自助终端**，依赖设备会话（`SessionId`/`dwDevSN`/`oidsession`）。常见动作：`PrintJob/PrintOut`、`PrintJob/CancelPrintOut`、`PrintJob/GetPrintOutList`、`Pay/CardPay`、`Copy/*`、`FeeStd/*`。**未实现**，`client.py::submit_print_job` 抛 `NotImplementedError` 并指向本节 |
| `system` | `DaoController`/`EmailController`/`MulLanController`/`ConfigController`/`TestController`/`UpateController`/`HelpController` | 3/15/18/15/2/3/4 | 系统管理/多语言/邮件/升级，其中 `Help/Get` 就是本文档的数据源（已用于 live 测试）；其余未实现 |
| `admin` | 7 个控制器 | 148 | 管理端（站点/任务/费率/服务器/管理员/记录），需管理员会话，**未实现** |
| `v1` | `SubsidyController` | 16 | 补助/`OPM*` 一卡通对接动作，**未实现** |

> 统计口径：文档共 **32 控制器 / 711 动作**（含重载重复项）。本库实现
> `client` 模块中约 24 个动作（含 8 个 Auth、3 个 Station、1 个 Paper、
> 9 个 PrintJob/CloudPrint、4 个 Scan、5 个 Report、1 个 FeeStd、4 个 Pay）。

---

## 6. 离线 / 在线测试对照

`src/test/pms/` 下的测试全部用 `unittest.mock` 伪造 `requests.Session`，
响应体严格按本文档 §1.2 的信封与 §4 的字段构造：

| 测试文件 | 覆盖 |
| --- | --- |
| `test_pms_auth.py` | PublicKey/GetAuthToken/Login 三步流、`szPassword` 的 RSA 结构与 nonce 拼接、登录失败 → `InvalidCredentials`、`Check` 的 `code=4` → `None`、`SessionExpired` 映射、`Logout` |
| `test_pms_client.py` | 根地址解析与环境变量覆盖、`pms()` 单例工厂、支付封装（`GetBill`/`Recharge`/`GetPayResult`/`WaitPayResult`）、`submit_print_job` 抛 `NotImplementedError`、`ChgPassword` body、`sso` 惰性导入降级路径 |
| `test_pms_models.py` | 各模型 `from_json` 容错（缺字段/None/脏类型）、时间与金额换算、`paper_name` 映射、`duplex` 判序、纸型单位换算 |
| `test_pms_stations.py` | `Station/GetList` 解析（含位图属性、纸盒、时间）、`GetSrvList`、空列表 |
| `test_pms_print.py` | `CloudPrint/Upload` multipart 字段、`PrintJob/Get` 解析（`szPaperDetail` 字符串→列表）、`Del` body、`PreviewPage` base64 解码 |
| `test_pms_scan.py` | `Scan/Get` 解析、`Download` 流式写盘 |
| `test_pms_report.py` | `Report/Stat`、`Report/DetailPage` 分页与金额换算 |
| `test_pms_live.py` | `@pytest.mark.live`：GET `/api.html` 200，解析其引用的 `Help/Get`，从中数出 ≥5 个控制器名 |

> 辅助文件（非测试用例）：`conftest.py`（`client`/`session` fixture）、
> `pms_fakes.py`（伪造 `requests.Session` 与响应信封）。

Live 测试默认被 `pyproject.toml` 的 `addopts = "-m 'not live'"` 排除；在校内网络下用
`pytest src/test/pms -m live` 单独跑。
