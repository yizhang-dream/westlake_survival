# 子模块同类问题审计（2026-10-27）

背景：游泳「做不了」的复盘得出五条根因（见
[2026-10-27-campus-booking-postmortem](https://answers.xn--ltr42g543b.cn/2026-10-27-campus-booking-postmortem.html)）。
本文把这五条当成检查单，逐条套到其余子模块，只记录**本次实测**能支撑的结论。

五条根因：

1. 把需求锚定到单一系统（「预约」= 预约中心）；
2. 把历史通知/旧记录当现状；
3. 「占位符指向外部系统」的模式没有外推；
4. 把「搜不到」当「不存在」（字典里没有 sportvenue）；
5. 没问用户「你平时从哪个入口办这件事」。

## 一、结论：同类问题不止游泳一处

| 模块 | 仓库先前说法 | 本次实测 | 归类 |
| --- | --- | --- | --- |
| 体育场馆/游泳 | 预约中心里 `state=1`，「不可预约」 | 真实入口 `sportvenue` 独立系统，登录链路已通；每天返回「表单规则未找到」 | 真做不了（服务端未配表单，非我们代码） |
| 图书馆座位 | 「另一套 seats.library，服务端驱动 UI，尚未接入」 | 前端是**汇图 zhishulib** 的产品（`api.huitu.zhishulib.com`），首页加载**企业微信 JSSDK**（`jwxwork`）+ `lab-user-data` 空 `accessToken`，登录走企微 OAuth 签名；浏览器直连拿不到 token | 逆向未做完（缺的是企微授权路径，不是接口） |
| 场馆预约（表单） | **未提及** | 办事大厅有独立应用「场馆预约」`infoplus/form/CGYY`，另有「资源预约」`ResourceReservation`、「会议室预约申请管理」`YY_JSSQXXGL`；均 CAS 登录，**发起即创建流程实例**（写操作），未探明字段 | 没建（且属写操作，需用户授权一次） |
| 选课 | 被视为「不做」的写操作，能力面不含 | ~~`westlake probe` 当场回「已授权（可开发选课功能！）」~~ **2026-10-27 当日推翻**：组件页 HTTP 200 但正文是「您无权访问该页面」，`probe` 只认英文 `not authorized`，把中文拒绝页误判成已授权 | 判断错 → 修正为**未授权**（选课车只读也打不开；中文文案已补进判定） |
| 办事/任务中心 | 记忆里标为「登录失败」阻塞项 | `westlake todo list` → 「没有待办任务」；`iam.login_for` 直登成功 | 判断错（旧结论已失效） |
| 评教/学工 | `sis-evals` 走 SIS 瓦片，视为唯一入口 | `eval.westlake.edu.cn`（CAS 登录后落 `/xsfw/sys/xggzptapp/*default/index.do#/gzzm`，学生服务/学工平台 SPA）此前**不在任何清单里** | 没建 + 没发现 |
| 财务 | `finance` 模块 = 财务部制度文章 | 制度站确实只是 `finance.westlake.edu.cn` 网站；报销单据状态不在这里，应走办事大厅流程 | 锚定偏差（制度 ≠ 系统） |
| OPAC 书目 | 公开检索不可用 | `westlake probe` 仍 HTTP 404；2026-10-27 复查连根路径 `/opac/` 也 404（此前 302→登录页），整个 OPAC webapp 已摘除 | 真不可用 |
| 就业服务网深列表 | 「需登录，暂未接入」 | 已接（`career deep`/`career detail`，统一密码自动登录、风控挡时降级匿名）：campus 20 条 / teachin 1 条 / news 8 条实测通 | 已建 |
| HPC 成果库 | 四通道全断 | 未重测 | 真断（历史结论） |

## 二、发现层缺陷：字典决定视野

这是本次唯一**可修的代码级**根因。实测证据：

- `CENSUS_HOSTS` / `_EXTRA_CANDIDATES` 里没有任何 venue/sport/seat 类词，
  所以 `sportvenue`、`seats.library` 从未进入 `/hosts` 普查——不是它们不可达，
  是我们的词表没写。两个域名实测都 200。
- 按「功能词」重写 232 个候选实测：解析成功 15 个，其中 **4 个不在服务注册表**
  （`chem`、`eval`、`finance`(模块已用但未登记)、`sportvenue`）。
- Wayback 历史索引（`archive_hosts`）只回来 **11 个域名**，缓存里也是 11 个——
  这条「历史索引」证据链实际是空的，不能当作覆盖面证明。
- CertSpotter 免费接口对 `westlake.edu.cn` 只回 21 张证书 / 11 个域名，
  证书透明度日志在当前额度下也无法当全量目录。
- 单级词表天然找不到 `seats.library` 这种二级名字。
- **二级子域曾被整体误判为 DEAD**：`_probe_one` 把「含点」当成「已是完整域名」，
  于是 `seats.library`、`eer.lab`、`m.hpc`、`new.hpc`、`old.hpc` 全被探测到裸主机名
  上并记为不可用。实测三者均为 200。清单里有数据、结论却是错的——比没数据更危险。

修法（已落地）：

1. `discovery.CENSUS_HOSTS` 补入 `sportvenue seats.library chem eval payment`；
2. `discovery.EVIDENCE_HOSTS` 登记「字典猜不到」的主机，新增系统先登记；
3. `discovery.evidence_hosts()` 读 Wayback/滚雪球/资产收割三份缓存并集；
   `snowball_hosts` / `asset_hosts` 现在会把结果落缓存（此前只有 archive 落）；
4. `hosts.candidate_hosts()` 合并四类来源（注册表 + 功能词 + CENSUS_HOSTS + 证据缓存）；
5. `hosts._EXTRA_CANDIDATES` 按「校园里存在什么服务」补 60 余个功能词；
6. `hosts._probe_one` 修二级子域拼接（现在一律补 `.westlake.edu.cn` 后缀）；
7. `westlake probe` 新增「场馆/座位入口」一项，`tools/host_hunt.py` 保留
   功能词扫描脚本，便于以后重跑。

实测覆盖变化：候选 126→197，存活 81→96（2026-10-27，同一台机器、同一网络）。

## 三、下一步（按代价从低到高）

1. **场馆预约 CGYY / 资源预约**：需用户在 i西湖 点开一次，或授权我发起一次
   流程看表单字段（会在账号里留一条流程实例）。
2. **图书馆座位**：确认是否在**企业微信**里打开（工作台 → 图书馆座位）。
   若是，接入方式应是企微授权而非浏览器登录；这条同样需要用户确认入口。
3. **eval 学生服务平台**：CAS 已能登，缺 `xsfw` 的菜单/API 面探测；
   若它含奖惩/勤工/困难认定，可能比 SIS 瓦片更全。
4. **选课只读查询**：`probe` 已确认组件授权，可做「可选课程/余量」查询；
   写入（选课/退课）仍按既定政策不做。
5. **财务**：明确「查制度」与「查单据」是两件事，后者走办事大厅 `todo/doing`。

## 四、方法沉淀

- 判断「做不了」之前，先跑 `westlake probe` 与 `westlake hosts list`，
  再查办事大厅 `westlake affairs apps <关键词>`——目录里往往有指向外部系统的
  占位应用（如「预约系统外链_勿动」）。
- 「搜不到」只能写进「我不知道」栏，不能当成「不存在」；
  第三栏「谁知道」通常就是用户（他平时从哪个 App/入口进）。
