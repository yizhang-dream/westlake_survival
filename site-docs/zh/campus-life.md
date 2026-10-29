# 校园生活

本页命令全部**无需账号**（除打印任务与门户卡片）。

## 校历 / 班车 / 快照

```bash
westlake calendar today        # 今天几号、第几周、事件
westlake calendar week 10      # 第 10 周一览
westlake calendar events       # 校历事件
westlake transit next          # 下一班校车
westlake transit table         # 班车时刻
westlake transit ical          # 班车 ICS（网页 /ical 一键复制）
westlake context               # 「此刻西湖」：周次+班车+天气+AQI+截止
westlake digest                # 晨报一条龙
```

`context` 默认档即含实时天气与空气质量（open-meteo，免 key）。

## 食堂 / 公寓 / 地图 / 电话

```bash
westlake campus dining         # 食堂与咖啡
westlake campus housing        # 公寓
westlake map [--campus 云谷]    # 校区地图 + 720° 全景 + 到校交通
westlake contact phones        # 常用电话
```

## 打印 / 门户 / 待办（需统一密码）

```bash
westlake pms stations          # 打印网点（免账号）
westlake pms jobs              # 我的打印任务
westlake portal cards          # 门户个人卡片（未读邮件/在借/待办）
westlake todo list|doing|done  # 任务中心
westlake affairs apps 预约      # 什么事在哪儿办（服务目录）
```
