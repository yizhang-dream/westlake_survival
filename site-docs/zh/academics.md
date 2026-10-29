# 学业：SIS 与 AMS

西湖大学包含两套教务教学系统，均接入统一身份认证：**SIS**（教务系统，基于 IAM OAuth2）与 **AMS**（教学系统，基于 IAM 统一认证，会话缓存 8 小时）。以下命令均须在校园网或 VPN 环境下执行。

## SIS 课表与考试

```bash
westlake sis schedule        # 课表节次（课程/教师/星期/时间/地点）
westlake sis grid            # 周课表网格 + 冲突检测（只读）
westlake sis ical            # 导出 .ics 订阅（网页 /ical 一键复制）
westlake sis exams           # 考试安排（时间/考场/座位）
```

`sis grid` 在冲突检测时会自动合并同一教学班分拆多间教室的平行排课记录；在选课开放阶段支持并入选课车节次进行时间重叠预检。本工具不提供选课、退课或抢课功能。

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

档案与资助（records/aid）包含 20 余项只读查询命令，可通过 `westlake find <关键词>` 检索对应命令。

## AMS 教学系统

```bash
westlake ams schedule --start 2026-10-27 --end 2026-11-01
westlake ams status          # 学籍与选课入口
westlake ams menus           # 服务入口清单
```

AMS 与 SIS 分属不同业务维度，两套课表数据各有侧重，均保持只读。
