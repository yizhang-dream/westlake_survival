"""异常体系：westlake_survival 所有错误的公共基类与具体异常。

约定：
- 业务代码只抛本模块中的异常（或其子类），不裸抛 requests/bs4 的异常。
- 调用方可以只捕获 ``WestlakeError`` 处理一切来自本库的错误。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests


class WestlakeError(Exception):
    """所有 westlake_survival 错误的基类。"""


class AuthError(WestlakeError):
    """认证/会话类错误。"""


class InvalidCredentials(AuthError):
    """用户名或密码错误。"""


class SessionExpired(AuthError):
    """会话已过期且自动刷新失败。"""


class OffCampusError(WestlakeError):
    """校外访问被拒：目标系统仅校园网/VPN 内可达。

    西湖大学多数业务系统（SIS、OPAC、打印等）只在校内网络可达，
    校外使用需先连接学校 VPN（https://vpn.westlake.edu.cn/）。
    """


class NotFound(WestlakeError):
    """请求的资源不存在（课程、文件、条目等）。"""


class ParseError(WestlakeError):
    """页面/接口返回内容与预期结构不符，解析失败。"""


class ActionError(WestlakeError):
    """业务动作被拒绝（选课冲突、预约失败、重复提交等）。"""


# 校外阻断页常见特征（西湖出口网关 / PeopleSoft ckreq 页）。
# 命中任一即视为校外访问被拒；随实测校准补充。
_OFFCAMPUS_MARKERS = (
    "Access forbidden, please contact administrator",
    "?cmd=login&errorPg=ckreq",
)

#: PeopleSoft 校外拦截跳转（302 → 登录失败页）的 Location 特征。
#: 只认 ckreq 这个西湖出口网关标志，避免把所有跳登录页都误判为校外。
_OFFCAMPUS_REDIRECT_MARKER = "errorPg=ckreq"


def is_offcampus(response: "requests.Response") -> bool:
    """判断一个响应是否是"校外访问被拒"阻断页。

    两种常见形态：

    - **403**：正文里出现阻断特征串（如 "Access forbidden" 或 ckreq 页）。
    - **301/302/303**：``Location`` 头跳向 ``?cmd=login&errorPg=ckreq``
      （PeopleSoft 校外拦截），此时特征在头里、正文没有。

    普通跳登录页（无 ckreq 特征）不算校外，返回 ``False``。
    """
    status = getattr(response, "status_code", 0)
    if status == 403:
        head = response.text[:1024] if response.text else ""
        return any(marker in head for marker in _OFFCAMPUS_MARKERS)
    if status in (301, 302, 303):
        location = response.headers.get("Location", "") or ""
        return _OFFCAMPUS_REDIRECT_MARKER in location
    return False
