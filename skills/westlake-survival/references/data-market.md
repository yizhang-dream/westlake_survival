# 门户数据市集：本人数据与数据目录

当用户查询个人履历、已修学分/课程、志愿记录，或询问门户“数据市集”有哪些数据时，使用本指南。已验证的七类查询由本技能的 [只读脚本](../scripts/data_market.py) 提供；尚无 `westlake market` 命令或专用 MCP 工具。

## 调用方法

先运行 `westlake doctor`，使用与 `westlake` 相同的 Python 解释器。下方 `<skill-root>` 指本技能 `SKILL.md` 所在目录，由 Agent 按实际安装位置替换；路径不依赖当前工作目录，也不限定操作系统。

安装时需复制完整技能目录，保留 `scripts/` 和 `references/`。仅生成或复制 `SKILL.md` 的编译/安装流程不携带本扩展的附件，需要另行复制这两个目录。

```bash
python "<skill-root>/scripts/data_market.py" catalog
python "<skill-root>/scripts/data_market.py" profile
python "<skill-root>/scripts/data_market.py" resume
python "<skill-root>/scripts/data_market.py" courses
python "<skill-root>/scripts/data_market.py" honors
python "<skill-root>/scripts/data_market.py" clubs
python "<skill-root>/scripts/data_market.py" volunteer
```

| 查询名 | 内容 | 命令行输出 |
| --- | --- | --- |
| `catalog` | 当前账号可见的数据集目录 | 全部分页的标题、主题、主管部门、更新频率；加 `--summary` 只输出数量和字段名 |
| `profile` | 本人基本/学籍档案 | 顶层字段数与字段名；包含关联字段、双语显示名和系统字段，不能视为等量的独立业务项 |
| `resume` | 本人个人履历 | 条数与字段名，包括学校、专业、学历/学位、学习形式和起止时间等 |
| `courses` | 本人已修课程 | 条数与字段名，包括课程编号、名称、学期、有效学分和分类 |
| `honors` | 本人已获荣誉 | 条数与字段名 |
| `clubs` | 本人学生社团记录 | 条数与字段名，区别于全校社团目录 |
| `volunteer` | 本人志愿服务 | 条数与字段名，包括名称、类型、时长和起止时间 |

脚本在一个进程内复用会话并遍历全部分页，空列表是有效结果；分页缺失、中断或数量不符时明确报错。`--page-size 5` 可用于需要小页分页的场景，缺省每页100条。多个查询应通过下方的进程内 API 复用一次登录，不要并发运行多个登录进程。

## 读取具体业务字段

命令行缺省只展示概要，避免把证件、联系方式和关联人员对象整包写进终端或对话。Agent 需要回答具体问题时，可按本机技能目录载入脚本，在进程内取值并只选择本次所需字段：

```python
import importlib.util
from pathlib import Path

skill_root = Path("<skill-root>")  # 替换为 SKILL.md 所在的实际目录
script = skill_root / "scripts" / "data_market.py"
spec = importlib.util.spec_from_file_location("westlake_data_market", script)
market = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market)

with market.MarketClient() as client:
    courses = client.fetch("courses")["content"]
    # 按问题选择字段；不输出完整个人档案或人员关联对象。
    for course in courses:
        print(course.get("kcmc"), course.get("xq"), course.get("yxxf"))
    volunteer = client.fetch("volunteer")["content"]
    print("志愿记录条数：", len(volunteer))
```

`fetch()` 返回服务器的 `data` 对象，业务内容在 `content`；分页查询还保留 `pageInfo`。`profile.content` 是字典，其余六类的 `content` 是列表。返回数据未脱敏，Agent 应按任务筛选字段，对第三方输出默认脱敏，不打印学号、证件号、联系方式或令牌。

## 数据目录与权限

2026-11-04 核验时，目录有36项、9类主题；这是当日观察，调用时以实时结果为准。目录覆盖人员、部门单位、学生管理、一卡通、房产、安防、预约中心、资产、财务。

值得进一步核对的目录项包括：

- 学生各课程类别已修学分与最低要求学分；论文、专利、科研获奖、竞赛获奖。
- 假期留校申请、一卡通卡户、房间使用、访客当天到访、资源预约。
- 设备资产、资产入库、财务项目基本信息与执行情况。

这些属于目录线索，尚未封装为上述七类查询。目录中的申请入口不代表底层明细已获授权；本脚本不发起申请，不读其他人员记录，也不提供人员编号或任意接口参数。需要申请、编辑或发起流程时，先按学校权限与项目写操作规则处理，不能把它当作普通查询。

页面定义包含教师、任职、科研等其他分组，但静态定义存在不代表当前学生账号可见。本人档案/已修课程/志愿等与 SIS 有交集；“已修课程”口径也不能直接与包含在修课程的成绩总数比较。目录中的一卡通卡户不等于已验证存在消费流水，财务项目也不等于个人报销单。

数据中台的目录原始链接为 `http://data.westlake.edu.cn:8778/`，2026-11-04 本机直连200，标题“数据中台”；默认HTTPS443不是该入口。首页可达与其中明细的数据授权分别判断。

## 认证与接口维护

[脚本](../scripts/data_market.py) 是请求路径、筛选方案与表达式参数的维护原件。入口为 [门户数据市集](https://my.westlake.edu.cn/main/child-frame/xsmhqdyy8572869360763225298/xueshengmenhushouye?titleName=%E6%95%B0%E6%8D%AE%E5%B8%82%E9%9B%86&otherPart=%E6%95%B0%E6%8D%AE%E5%B8%82%E9%9B%86&urlLink=%2Fmain%2Fchild-frame%2Fshujushiji3173474984560511355%2Fshujushiji3173474984560511355%2Fshishengjibenxinxi&tenantCode=cop)。

认证过程如下：

1. GET 门户 `/service/portal/main/pc-user-info?ioa=0&locale=zh_CN`，取响应的官方 `redirectUrl`。
2. 从本机 `read_credentials()` 读取已配置账号，通过现有 `iam.login_for()` 登录，使用 `direct_session()` 直连。验证码状态必须明确关闭；未明确或已启用时停止，不提交密码认证。
3. IAM 回跳 `/login/third-auth/code` 后，按官网调用 GET `/service/ctp-user/auth/refresh-token`，传回跳的 `code` 与 `redirectUri`，取得门户 Cookie。
4. 再查 `pc-user-info`，以存在 `USER_INFO_MAP` 确认登录成功。仅运行 `iam.login_for()` 不足以完成门户自己的会话交换。

Cookie、密码和OAuth参数只在进程内使用，不落盘，不输出。认证失败后不自动换密码、反复登录或回退其他账号。

业务查询统一位于 `/service/shujushiji3173474984560511355/shishengjibenxinxi`：本人档案与履历走页面微流，列表走页面的 `filter-plan` 路由，保留当前账号表达式和后端筛选方案。方案标识及表达式键取自真实页面请求，不接受用户覆盖或任意人员编号。

不要根据 `remoteEntry` 中残留的 `graphql:"/service/graphql"` 推断查询协议；2026-11-04 该地址实测404，正常页面使用的是脚本中的REST接口。404、权限或响应结构变化时，重新核对官方页面真实请求，不尝试猜方案编号或删除账号条件。
