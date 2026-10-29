# 学术与就业

## 学术资源（scholar）

```bash
westlake scholar dbs               # 订阅数据库注册表
westlake scholar open cnki         # 数据库访问入口
westlake scholar campus            # 校园网络环境检测
westlake scholar doi 10.1038/... -o out.pdf   # DOI → PDF 全文（校园网订阅通道）
westlake scholar ensure            # 校外访问：通过 CARSI 建立数据库访问会话
```

`scholar ensure` 依赖 `[browser]` 可选依赖；其余数据库查询无需账号（校园网内通过 IP 自动授权）。

## 培养方案（program）

```bash
westlake program plan [专业]       # 学分要求 + 课程表
westlake program curriculum       # 课程体系
westlake program majors           # 专业列表
westlake program courses          # 通识课程目录
westlake program course 机器学习    # 跨源课程搜索
```

## 科研支撑

```bash
westlake research latest          # 科研进展
westlake faculty search 关键词     # 导师名录
westlake hpc overview             # HPC 集群队列
westlake finance sections         # 报销与经费制度
westlake news                     # 官网新闻
westlake events                   # 讲座活动
```

## 就业

```bash
westlake careers                  # 最新招聘岗位
westlake career deep --kind campus|jobfair|teachin   # 招聘专栏深列表
westlake career detail <id>       # 招聘详情
```
