"""凭据读取：四级优先级（内存 > 环境变量 > 系统钥匙串 > 配置文件）。

安全约定：凭据只在需要时读入内存，绝不写日志、绝不随会话落盘。
配置文件写盘时尽力设为 ``0600``（Windows 下 chmod 语义有限，尽力而为）。

系统钥匙串（Windows Credential Manager、macOS Keychain、Linux Secret Service
等）通过可选的第三方 ``keyring`` 库访问。未安装 ``keyring`` 时本模块行为与
此前完全一致（钥匙串一级整体跳过）。
"""

from __future__ import annotations

import os
from pathlib import Path

from westlake_survival._cache import config_root
from westlake_survival.exceptions import AuthError

#: 环境变量名，格式 ``sid:password``。
ENV_VAR = "WESTLAKE_CREDENTIALS"

#: 配置文件相对 ``config_root()`` 的名字，格式 ``sid:password``。
FILENAME = "credentials.txt"

#: 钥匙串中的固定 service 名；用户名即学号（username=sid）。
KEYRING_SERVICE = "westlake_survival"

#: 钥匙串里记录「当前学号」的保留用户名。钥匙串按 (service, username) 索引，
#: 读取时必须先知道 username=sid，故额外存一条 *sid* 指针；``__westlake__``
#: 作为保留名与实际学号（纯数字/字母）不可能撞车。
KEYRING_SID_KEY = "__westlake__"

#: 进程内凭据（最高优先级）。空 dict 表示未设置。
_MEMORY: dict[str, str] = {}

_GUIDE = (
    "未找到可用凭据。请任选一种方式提供（优先级从高到低）：\n"
    "  1) 进程内：westlake_survival.sso.cred_set(sid, password)\n"
    f"  2) 环境变量：export {ENV_VAR}='学号:密码'\n"
    "  3) 系统钥匙串：westlake_survival.sso.save_credentials_keyring(sid, password)\n"
    "     （需安装 keyring 库，如 pip install 'westlake_survival[secure]'）\n"
    "  4) 配置文件：westlake_survival.sso.write_credentials(sid, password)\n"
    "     （写入 ~/.westlake_survival/credentials.txt，格式 学号:密码）"
)


def cred_path() -> Path:
    """返回凭据配置文件路径（不创建文件）。"""
    return config_root() / FILENAME


def cred_set(sid: str, password: str) -> None:
    """把凭据放进进程内存（最高优先级，退出即丢失）。"""
    _MEMORY["sid"] = sid
    _MEMORY["password"] = password


def cred_clear() -> None:
    """清除内存中的凭据（不影响环境变量与配置文件）。"""
    _MEMORY.clear()


# --------------------------------------------------------------------------- #
# 系统钥匙串（可选后端，经 ``keyring`` 库）
# --------------------------------------------------------------------------- #
#
# 设计说明：钥匙串按 ``(service, username)`` 二元组索引，而读取侧接口
# :func:`read_credentials_keyring` 不接受 sid 参数，因此除按 ``username=sid``
# 存密码外，另存一条保留项 ``(KEYRING_SERVICE, KEYRING_SID_KEY) -> sid`` 作为
# 指针，读取时先取指针再取密码。``keyring`` 是可选依赖：所有函数都惰性导入，
# 任何导入/调用异常一律按「不可用」处理，绝不向调用方抛出。


def keyring_available() -> bool:
    """``keyring`` 是否可用（已安装且可导入）。

    惰性导入并捕获一切异常（未安装、后端初始化失败等）后返回 ``False``。
    """
    try:
        import keyring  # noqa: F401
    except Exception:
        return False
    return True


def save_credentials_keyring(sid: str, password: str) -> bool:
    """把凭据写入系统钥匙串（``service=westlake_survival``，``username=sid``）。

    成功返回 ``True``；``keyring`` 不可用或写入抛异常时返回 ``False``。
    同时写入一条指向当前学号的指针项，供 :func:`read_credentials_keyring` 使用。
    """
    try:
        import keyring
    except Exception:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, sid, password)
        keyring.set_password(KEYRING_SERVICE, KEYRING_SID_KEY, sid)
    except Exception:
        return False
    return True


def read_credentials_keyring() -> tuple[str, str] | None:
    """从系统钥匙串读取 ``(sid, password)``；不可用或未存时返回 ``None``。

    任何导入/调用异常都按不可用处理（返回 ``None``），由调用方回退下一级。
    """
    try:
        import keyring
    except Exception:
        return None
    try:
        sid = keyring.get_password(KEYRING_SERVICE, KEYRING_SID_KEY)
    except Exception:
        return None
    if not sid or not sid.strip():
        return None
    try:
        password = keyring.get_password(KEYRING_SERVICE, sid)
    except Exception:
        return None
    if not password:
        return None
    return sid, password


def delete_credentials_keyring() -> bool:
    """删除钥匙串中的凭据（密码项与学号指针项）；成功返回 ``True``。

    ``keyring`` 不可用或后端删除失败时返回 ``False``。仅当条目**存在**时才调用
    删除，故「本就不存在」不算失败。
    """
    try:
        import keyring
    except Exception:
        return False
    try:
        sid = keyring.get_password(KEYRING_SERVICE, KEYRING_SID_KEY)
        targets = [
            name
            for name in (sid, KEYRING_SID_KEY)
            if name and keyring.get_password(KEYRING_SERVICE, name) is not None
        ]
        for name in targets:
            keyring.delete_password(KEYRING_SERVICE, name)
    except Exception:
        return False
    return True


def _parse(raw: str, source: str) -> tuple[str, str]:
    """把 ``sid:password`` 解析为二元组。

    分隔符取**第一个** ASCII 冒号；若整行没有 ASCII 冒号但含中文全角冒号
    ``：``，则以全角冒号兜底切分（防用户误输入中文标点）。
    """
    text = raw.strip()
    if not text:
        raise AuthError(f"凭据为空（来源：{source}）。\n{_GUIDE}")
    idx = text.find(":")
    if idx < 0:
        idx = text.find("：")
    if idx < 0:
        raise AuthError(f"凭据格式应为 sid:password，实际缺少分隔符（来源：{source}）。\n{_GUIDE}")
    sid = text[:idx].strip()
    password = text[idx + 1 :].strip()
    if not sid or not password:
        raise AuthError(f"凭据的学号或密码为空（来源：{source}）。\n{_GUIDE}")
    return sid, password


def read_credentials() -> tuple[str, str]:
    """按四级优先级返回 ``(sid, password)``；都无则抛 :class:`AuthError`。

    优先级：内存 > 环境变量 > 系统钥匙串（``keyring`` 可用时）> 配置文件。
    钥匙串读取异常按不可用处理，自动回退到配置文件。
    """
    if _MEMORY.get("sid") and _MEMORY.get("password"):
        return _MEMORY["sid"], _MEMORY["password"]

    env = os.environ.get(ENV_VAR)
    if env and env.strip():
        return _parse(env, f"环境变量 {ENV_VAR}")

    if os.environ.get("WESTLAKE_NO_KEYRING"):
        # 测试/自动化隔离：完全无视系统钥匙串（读也不读），保证用例与真实凭据互不可见。
        keyring_creds = None
    else:
        keyring_creds = read_credentials_keyring()
    if keyring_creds is not None:
        return keyring_creds

    path = cred_path()
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - 依赖文件系统状态
            raise AuthError(f"读取凭据文件失败：{path}（{exc}）。\n{_GUIDE}") from exc
        return _parse(raw, str(path))

    raise AuthError(_GUIDE)


def write_credentials(sid: str, password: str) -> Path:
    """把凭据写入 ``~/.westlake_survival/credentials.txt``（格式 ``sid:password``）。

    写盘后尽力设为 ``0600``；Windows 上权限语义有限，失败静默忽略。
    """
    path = cred_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{sid}:{password}", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows 上通常静默失败
        pass
    return path


__all__ = [
    "ENV_VAR",
    "FILENAME",
    "KEYRING_SERVICE",
    "cred_set",
    "cred_clear",
    "read_credentials",
    "write_credentials",
    "cred_path",
    "keyring_available",
    "save_credentials_keyring",
    "read_credentials_keyring",
    "delete_credentials_keyring",
]