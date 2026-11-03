# 高壁垒服务接入注记

一部分校内服务入口隐蔽、无公开文档，或需要自行分析网络请求才能程序化调用。本页记录这类服务的接入要点与命令入口，与 [ams.md](ams.md)、[sports.md](sports.md) 同属深挖注记。

## 学校 GPU 集群大模型对话（`westlake hpc chat`）

HPC 运营 OpenAI 兼容 AI 网关（`https://hpc-api.westlake.edu.cn/v1`），提供 DeepSeek、GLM、Qwen 等开源模型，校内免费使用。

- 接入要点：
  - 基于统一身份认证的 NewAPI 令牌自动申请与同步（`westlake hpc sync-key`；网关仅校园网/VPN 可达）；
  - 解析 Reasoning 思考过程与 Content 内容双通道流式协议，支持 `--think / --no-think` 开关。
- 用法：

  ```bash
  # 终端流式对话（默认 deepseek-flash，免外部 API key）
  westlake hpc chat "用一句话介绍西湖大学的办学定位"

  # 指定模型与系统提示词
  westlake hpc chat "写一个 Python 正则匹配函数" --model glm-flash --no-think
  ```
- MCP 工具：`hpc_chat`，外部 Agent 可直接调起集群模型执行推理。

## 官方「西湖 AI 问答」（`westlake portal ask`）

校内官方基于 Dify 引擎的问答助手（`https://chatbot.westlake.edu.cn`），沉淀图书馆规程、班车时刻、报销流程、办事入口等权威答复，原本只在门户深处以 iframe 展示。

- 接入要点：WebApp Passport 握手（`X-App-Code` 请求头 + `GET /api/passport` 获取访问令牌，取自其前端源码），打通 `POST /api/chat-messages` 的 blocking 与 SSE 流式请求，免账号密码登录。
- 用法：

  ```bash
  westlake portal ask "图书馆开放时间与借书规则"
  westlake portal ask "班车时刻在哪里查？"
  ```
- MCP 工具：`portal_ask`，可直接调取官方校内知识库。

## 大型科研仪器共享平台检索（`westlake instrument`）

全校生物、化学、物理、工学、微纳平台的实验仪器（透射电镜、冷冻电镜、高分辨质谱、核磁共振等）托管在基理系统（`share.westlake.edu.cn/genee/`），网页端缺乏快捷检索。

- 接入要点：AJAX 检索分页接口 `AJAX/Wias/Equipment/getEquipments/{start}`，结构化提取仪器名称、放置房间、联系人、电话及预约链接。
- 用法：

  ```bash
  # 检索仪器类型，返回房间、负责老师、电话与预约链接
  westlake instrument search "冷冻电镜"
  westlake instrument search "质谱" --limit 5

  # 浏览全校大仪最新清单
  westlake instrument list --limit 15
  ```
- MCP 工具：`instrument_search`。

## 网上办事大厅表单直达（`westlake affairs app`）

办事大厅（one.westlake.edu.cn）有 176 个流程应用，原生列表只显示名称与部门：

```bash
westlake affairs apps 证明     # 带关键词时自动打印直达链接
westlake affairs app 生物安全  # 流程详情说明、编号与直接填表 URL
```

注：`affairs portal`（门户大厅视图）接口近期因服务端变更暂不可用。

## 校园生活服务网点（`westlake campus services`）

```bash
westlake campus services --campus 云谷
```

覆盖云谷校区（实测）：

- 校园超市：C19#1楼（人工 09:00-21:00，24 小时无人自助）
- 快递驿站：C12-105 菜鸟驿站（每日 8:30-20:30，其余无人自助）；学术环 E6 负一层材料供应中心旁驿站（24h 刷校园卡进入）
- 干洗洗衣：C13-107（周一至周六 8:00-17:00，其余无人自助）
- 理发服务：C12-101（周一至周六 10:30-21:30）
- 图文打印：C12-103（周一至周五 8:30-17:30）
- 银行网点：C1#1楼近 C16（周一至周五 09:30-17:30）
- 自动售卖机：学术环各门厅、A2 服务大厅、C11-C15 公寓、H4 公寓、H5 食堂、二期篮球场等

## 能力发现

- `westlake find` 为上述服务内置口语同义词映射（`ai`、`大模型`、`chat`、`问答`、`仪器`、`电镜`、`质谱`、`核磁`、`办事` 等），口语输入即可命中相关命令与工具；
- `westlake doctor` 会检查集群 AI 令牌配置状态，未配置时输出修复引导。
