"""网络层公共配置：UA、超时、共享 Session 工厂。

所有发 HTTP 请求的模块应从这里取 UA 与超时参数，保证行为一致、
可被学校侧识别为一个统一客户端。
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from westlake_survival._version import __version__

#: 统一 User-Agent；带上项目名与参考仓库，方便学校侧排查时识别。
USER_AGENT = f"westlake_survival/{__version__} (+https://github.com/dumixthestpd/sustech_survival)"

#: 常规请求默认超时（秒）。
DEFAULT_TIMEOUT = 15.0

#: 登录/提交等敏感动作的短超时（秒）。
AUTH_TIMEOUT = 20.0

#: 自动重试次数（网络层错误，不含业务失败）。
RETRY_ATTEMPTS = 2


@dataclass(frozen=True)
class NetworkTimeouts:
    """各档超时参数；测试时可注入自定义值。"""

    default: float = DEFAULT_TIMEOUT
    auth: float = AUTH_TIMEOUT


def http_session(**session_kwargs) -> requests.Session:
    """创建一个带统一 UA 的 :class:`requests.Session`。"""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    for key, value in session_kwargs.items():
        if key == "headers":
            session.headers.update(value)
        else:
            setattr(session, key, value)
    return session
