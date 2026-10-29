# 学术与就业

## 学术资源（scholar）

```bash
westlake scholar dbs               # 订阅数据库注册表
westlake scholar open cnki         # 某库入口
westlake scholar campus            # 校园 IP 信标（现在校内吗）
westlake scholar doi 10.1038/... -o out.pdf   # DOI → PDF 全文（校园网订阅通道）
westlake scholar ensure            # 校外：CARSI 联盟 SSO 一条命令拉活会话
```

`scholar ensure` 需 `[browser]` 可选增强；其余免账号（校园网内出版社按 IP 认账）。

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
westlake career deep --kind campus|jobfair|teachin   # 深列表
westlake career detail <id>       # 详情
```
