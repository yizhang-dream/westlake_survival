# 西湖大学高壁垒隐性服务开扩与指令化落地报告

## 1. 目标与背景

在日常科研、学习与校园生活中，西湖大学存在大量具有极高实用价值，但入口隐蔽、无公开文档或需要复杂协议解析的内部服务。用户往往需要花费较多时间自行分析网络请求、解密 SSO 流程或探测接口。

本项目将此类内部高壁垒服务在 API 层面进行收敛，逆向并固化为开箱即用的指令与 Python 接口，降低师生与 Agent 接入成本，涵盖算力集群、官方 AI、科研仪器与办事流程。

---

## 2. 本轮开扩与指令化的四大高壁垒服务

### 学校 GPU 集群大模型对话（`westlake hpc chat`）
- **痛点**：HPC 运营着完整的 OpenAI 兼容 AI 网关（`https://hpc-api.westlake.edu.cn/v1`），支持 DeepSeek、GLM、Qwen 等开源模型。此前用户不仅缺乏自动化凭据配置，调用时也需要处理复杂的 Reasoning 思考流。
- **逆向成果**：
  * 打通基于校内统一身份认证的 NewAPI 令牌自动申请与同步（`westlake hpc sync-key`）；
  * 解析了校内集群模型的 Reasoning 思考过程与 Content 内容双通道流式协议。
- **开箱即用指令**：
  ```bash
  # 终端流式对话（默认 deepseek-flash，免外部 API key，校内免费）
  westlake hpc chat "用一句话介绍西湖大学的办学定位"
  
  # 指定模型与系统提示词，支持 --think / --no-think
  westlake hpc chat "写一个 Python 正则匹配函数" --model glm-flash --no-think
  ```
- **Agent 工具**：MCP 新增 `hpc_chat`，外部代理（如 Claude / ZCode）可直接调起西湖集群模型执行复杂推理。

---

### 官方「西湖 AI 问答」机器人协议逆向与一键提问（`westlake portal ask`）
- **痛点**：校内官方搭建了基于 Dify 引擎的智能问答助手（`https://chatbot.westlake.edu.cn`），沉淀了权威的图书馆规程、班车时刻、报销流程、办事入口。但此前该服务只在门户深处以 iframe 展示，外部无法程序化调用。
- **逆向成果**：
  * 解析其 WebApp 专用的 Passport 握手协议（`X-App-Code: xSifJnQclqHg4BQs` + `GET /api/passport` 获取访问令牌）；
  * 打通 `POST /api/chat-messages` 的 blocking 与 SSE streaming 请求链，免账号密码登录。
- **开箱即用指令**：
  ```bash
  # 直接向官方助手提问，流式获取权威答复与内网办理链接
  westlake portal ask "图书馆开放时间与借书规则"
  westlake portal ask "班车时刻在哪里查？"
  ```
- **Agent 工具**：MCP 新增 `portal_ask`，支持 Agent 在处理用户咨询时直接调取官方校内知识库。

---

### 全校大型科研仪器共享平台检索（`westlake instrument`）
- **痛点**：全校生物、化学、物理、工学、微纳各平台的实验仪器（透射电镜、冷冻电镜、高分辨质谱、核磁共振等）托管在基理系统（`share.westlake.edu.cn/genee/`），网页端缺乏快捷检索，查找仪器位置与管理员联系方式较为耗时。
- **逆向成果**：
  * 解析底层 AJAX 检索与分页接口 `AJAX/Wias/Equipment/getEquipments/{start}`；
  * 实现了按关键词结构化提取仪器名称、放置房间（学术环E区等）、联系人、电话及直达预约链接。
- **开箱即用指令**：
  ```bash
  # 检索特定仪器类型，秒级返回实验室房间、负责老师、电话与预约链接
  westlake instrument search "冷冻电镜"
  westlake instrument search "质谱" --limit 5
  
  # 浏览全校大仪最新清单
  westlake instrument list --limit 15
  ```
- **Agent 工具**：MCP 新增 `instrument_search`，支持 Agent 按实验需求快速定位设备地点与联系方式。

---

### 网上办事大厅表单直达与应用详情（`westlake affairs app`）
- **痛点**：办事大厅（one.westlake.edu.cn）拥有 176 个流程应用，此前列表只显示名称与部门，用户缺乏具体表单的直达链接和使用说明。
- **开箱即用指令**：
  ```bash
  # 带关键词时自动打印直达链接
  westlake affairs apps 证明
  
  # 查看某个流程的详细说明、编号与直接填表 URL
  westlake affairs app 生物安全
  ```

---

### 校园生活服务网点全景（`westlake campus services`）
- **痛点**：师生经常需要查找取快递地点、干洗衣服、理发、买生活用品等，原系统仅支持食堂与公寓。
- **开箱即用指令**：
  ```bash
  # 查询云谷校区生活服务网点（超市/快递/干洗/理发/打印/银行）
  westlake campus services --campus 云谷
  ```
- **覆盖网点清单**：
  * **校园超市**：C19#1楼（人工 09:00-21:00，24 小时无人自助）；
  * **快递驿站**：C12-105 菜鸟驿站（每日 8:30-20:30，其余无人自助）；学术环 E6 负一层材料供应中心旁驿站（24h 刷校园卡进入）；
  * **干洗洗衣**：C13-107（周一至周六 8:00-17:00，其余无人自助）；
  * **理发服务**：C12-101（周一至周六 10:30-21:30）；
  * **图文打印**：C12-103（周一至周五 8:30-17:30）；
  * **银行网点**：C1#1楼近 C16（周一至周五 09:30-17:30）；
  * **自动售卖机分布**：学术环各门厅、A2 服务大厅、C11-C15 公寓、H4 公寓、H5 食堂、二期篮球场等。

---

## 3. 全局能力路由升级与发现

为了防止「新功能做好了，用户和 Agent 依然不知道怎么搜」的问题，同步完成了全链路路由升级：

1. **同义词扩容（`capabilities.py`）**：
   `westlake find` 新增 13 组口语词映射（`ai`、`大模型`、`chat`、`问答`、`仪器`、`设备`、`电镜`、`质谱`、`核磁`、`办事`、`流程`、`表单`）。用户说「我要用集群大模型」或「查一下核磁仪器」，输入口语即可一键命中所有相关命令与工具。
2. **SKILL.md 核心路由表更新**：
   在能力总表中将 `hpc chat`、`hpc sync-key`、`portal ask`、`instrument search`、`affairs app` 明确列为顶层推荐指令。
3. **环境自检（`doctor`）联动**：
   `westlake doctor` 自动检查集群 AI 令牌配置状态，并在未配置时输出修复引导。

---

## 4. 验证与交付

1. **真实链路端到端冒烟**：
   运行 `tools/module_smoke.py`，新增的 4 类只读链路（`hpc chat`、`portal ask`、`instrument search`、`affairs app`）全部返回真实数据，测试通过率 100%。
2. **Web 界面与文档构建**：
   `tools/webui_smoke.py` 全量 32 页全部 200；`mkdocs build --strict` 严格构建 0 警告通过。
3. **隐私安全扫描**：
   `tools/pii_scan.py` 扫描全仓 533 个文件，无真实学号、私钥泄露。
