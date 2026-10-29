# 学业：SIS 与 AMS

西湖有两套教学系统，统一密码都通：**SIS**（教务，IAM OAuth2）与 **AMS**（教学系统，IAM 统一认证，会话缓存 8 小时）。以下命令均需校园网/VPN。

## SIS 课表与考试

```bash
westlake sis schedule        # 课表节次（课程/教师/星期/时间/地点）
westlake sis grid            # 周课表网格 + 冲突检测（只读）
westlake sis ical            # 导出 .ics 订阅（网页 /ical 一键复制）
westlake sis exams           # 考试安排（时间/考场/座位）
```

`sis grid` 的冲突检测会把「同一节课按班级拆多间教室」的平行条目排除（不算冲突）；选课窗口开放后可把选课车节次并入预检——**不做 add/drop/抢课**。

## 成绩与选课车

```bash
westlake sis grades          # 成绩单（GPA 估算）
westlake sis cart            # 选课车（只读；窗口未开时组件无权限属正常）
```

## 评教 / 第二课堂 / 学籍档案

```bash
westlake sis-evals list --pending     # 待评教
westlake records second-class        # 第二课堂成绩单
westlake records advisor             # 学业导师
westlake records other-apps          # 学籍异动等申请
westlake profile info|academic|extended   # 个人三档信息
```

records/aid 系列共 20+ 条只读命令，不确定就用 `westlake find <关键词>`。

## AMS 教学系统

```bash
westlake ams schedule --start 2026-10-27 --end 2026-11-01
westlake ams status          # 学籍与选课入口
westlake ams menus           # 服务入口清单
```

与 SIS 是两套课表（数据各有侧重），都只读。
