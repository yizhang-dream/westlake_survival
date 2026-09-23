"""pms —— 西湖大学图书馆自助文印（联创云打印）子模块。

目标系统是图书馆自助文印控制器 ``http://print.lib.westlake.edu.cn:9130``
（联创 UniOpm 云打印）。控制器自带 API 文档页 ``/api.html``，但它是 JS 壳，
真正的文档在 ``GET /api/system/Help/Get``（HTTP 200，约 360 KB，覆盖
client / selfservice / admin / system 四个模块）；本文档的端点清单已提炼到
同目录 :file:`api_notes.md`。

典型用法::

    from westlake_survival.pms import pms

    client = pms()                       # 单例；凭据登录时按需从 sso 读取
    client.list_stations()               # 网点列表（无需登录）
    client.list_papers()                 # 可用纸型（无需登录）
    client.login()                       # PublicKey → GetAuthToken → Login
    client.list_print_jobs()             # 我的打印任务
    client.upload("hw.pdf", copies=2)    # 上传并创建打印任务
    client.list_scan_jobs()              # 我的扫描文档
    client.usage_stat()                  # 累计用量
    client.usage_records(type=1)         # 消费明细（分页）

如果需要显式凭据::

    client = pms(username="20210000", password="...")

安全约定：凭据只在登录时读入内存，绝不写盘/写日志；:class:`PMSClient`
的支付相关方法（``recharge`` / ``get_bill``）会真实影响一卡通余额，调用前
务必阅读其 docstring。
"""

from __future__ import annotations

from westlake_survival.pms.client import (
    BASE_ENV_VAR,
    PAPER_AUTO,
    PMS_BASE,
    PMSClient,
    default_credentials,
    encrypt_password,
    resolve_base_url,
    rsa_public_numbers,
)
from westlake_survival.pms.models import (
    CHINA_TZ,
    Paper,
    PrintJob,
    ScanJob,
    Station,
    UsagePage,
    UsageRecord,
    UsageSummary,
    parse_paper_detail,
)

__all__ = [
    "BASE_ENV_VAR",
    "CHINA_TZ",
    "PAPER_AUTO",
    "PMS_BASE",
    "PMSClient",
    "Paper",
    "PrintJob",
    "ScanJob",
    "Station",
    "UsagePage",
    "UsageRecord",
    "UsageSummary",
    "default_credentials",
    "encrypt_password",
    "pms",
    "parse_paper_detail",
    "reset_pms",
    "resolve_base_url",
    "rsa_public_numbers",
]

_singleton: PMSClient | None = None


def pms(
    username: str | None = None,
    password: str | None = None,
    **kwargs,
) -> PMSClient:
    """返回共享的 :class:`PMSClient` 单例（首次调用时创建）。

    传入 *username* / *password* （或任意 :class:`PMSClient` 关键字参数）会
    重建单例，便于测试或切换账号。
    """
    global _singleton
    if _singleton is None or username is not None or password is not None or kwargs:
        _singleton = PMSClient(username=username, password=password, **kwargs)
    return _singleton


def reset_pms() -> None:
    """清空单例（测试用）。"""
    global _singleton
    _singleton = None
