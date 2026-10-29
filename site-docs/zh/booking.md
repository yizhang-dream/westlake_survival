# 场地预约与体育场馆

## 预约中心（统一密码 OIDC 自动登录）

17 类场地：自习室、研讨室、研习仓、琴房、活动用房等。

```bash
westlake booking types                  # 分类
westlake booking list --type 图书馆      # 该类资源
westlake booking days <房间> --start ... --end ...   # 逐日可约
westlake booking slots <房间> --date 2026-11-01      # 逐格空闲
westlake booking mine                   # 我的预约
westlake booking book <房间> --date ... --start 10:00 --end 11:00 --dry-run  # 预检
westlake booking book ... --yes         # 预约（consequence 确认门）
westlake booking cancel <预约号> --reason ... --yes  # 取消
```

没权限的分类只返回空列表——能不能约以 `booking types` 为准。

## 体育场馆 / 游泳（独立正元系统，只读）

```bash
westlake sport scenes            # 场景
westlake sport sites <场景>      # 场地
westlake sport days <场景> <场地>   # 逐日可约
westlake sport mine              # 我的预约
```

下单涉次卡支付，未接（刻意只读）。

## 边界说明

体育场馆与图书馆座位在另外的系统，不在预约中心里；四套系统对照见 [module_audit](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/module_audit_2026-10-27.md)。图书馆借阅因系统迁移暂不可用（[迁移说明](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/library_migration_2026-10-28.md)）。
