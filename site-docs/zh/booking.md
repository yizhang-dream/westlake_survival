# 场地预约与体育场馆

## 预约中心（统一身份认证 OIDC 登录）

17 类场地：自习室、研讨室、研习仓、琴房、活动用房等。

```bash
westlake booking types                  # 分类
westlake booking list --type 图书馆      # 该类资源
westlake booking days <房间> --start ... --end ...   # 逐日可约
westlake booking slots <房间> --date 2026-11-01      # 逐格空闲
westlake booking mine                   # 我的预约
westlake booking book <房间> --date ... --start 10:00 --end 11:00 --dry-run  # 预检
westlake booking book ... --yes         # 预约（consequence 确认拦截）
westlake booking cancel <预约号> --reason ... --yes  # 取消
```

对于当前账号无权限的场地类别，接口返回空列表；具体可预约类型以 `booking types` 输出为准。

## 体育场馆与游泳场地（只读）

```bash
westlake sport scenes            # 场景
westlake sport sites <场景>      # 场地
westlake sport days <场景> <场地>   # 逐日可约
westlake sport mine              # 我的预约
```

场地预订涉及线下次卡与支付流程，本工具仅提供状态查询，不执行预约下单。

## 边界说明

体育场馆与图书馆座位属于独立系统，未并入统一预约中心；各预约系统的业务归属与接口对照详见 [module_audit](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/module_audit_2026-10-27.md)。图书馆系统因厂商平台迁移，借阅相关接口暂不可用（详见 [迁移说明](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/library_migration_2026-10-28.md)）。
