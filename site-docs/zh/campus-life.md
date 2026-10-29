# 校园生活

除自助打印任务与门户个人卡片需登录外，本页功能均**无需账号**。

## 校历 / 班车 / 快照

```bash
westlake calendar today        # 今天几号、第几周、事件
westlake calendar week 10      # 第 10 周一览
westlake calendar events       # 校历事件
westlake transit next          # 下一班校车
westlake transit table         # 班车时刻
westlake transit ical          # 班车 ICS（网页 /ical 一键复制）
westlake context               # 当前状态快照：周次、班车、天气与待办截止
westlake digest                # 每日综合信息摘要
```

`context` 默认级别包含实时气温与空气质量数据（基于 Open-Meteo 接口）。

## 食堂 / 公寓 / 地图 / 电话

```bash
westlake campus dining         # 食堂与咖啡
westlake campus housing        # 公寓
westlake map [--campus 云谷]    # 校区地图 + 720° 全景 + 到校交通
westlake contact phones        # 常用电话
```

## 打印 / 门户 / 待办（需统一身份认证）

```bash
westlake pms stations          # 打印网点（免账号）
westlake pms jobs              # 我的打印任务
westlake portal cards          # 门户个人卡片（未读邮件/在借/待办）
westlake todo list|doing|done  # 任务中心
westlake affairs apps 预约      # 事务指南（服务目录检索）
```
