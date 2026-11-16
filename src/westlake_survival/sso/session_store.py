"""受保护的本地会话存储：Windows 下使用 DPAPI 用户密钥加密，POSIX 下原子写 0600 权限文件。

各业务模块（Canvas Cookie、Booking OIDC Token、SIS PS_TOKEN、AMS Cookie、
图书馆 userJwt）统一经本模块存取短期会话数据，落盘路径收敛在
``<config_root>/sessions/<service>.bin``，避免明文凭据/令牌散落于配置根目录，
并支持自动迁移与清理历史明文会话文件。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from westlake_survival._cache import config_root

__all__ = [
    "clear_session_data",
    "load_session_data",
    "save_session_data",
]

_SERVICE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DPAPI_PREFIX = b"WLDPAPI1:"
_PLAIN_PREFIX = b"WLPLAIN1:"
_DPAPI_ENTROPY = b"westlake-survival-session-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01

#: 历史明文会话文件相对路径，用于首次读取/写入/清理时自动迁移并清除。
_LEGACY_REL_PATHS: dict[str, tuple[str, ...]] = {
    "canvas": ("canvas_cookies.json",),
    "booking": ("booking_session.json",),
    "sis": ("sis_cookies.json",),
    "ams": ("ams_cookies.json",),
    "mylib": ("cache/lib/user_jwt.json",),
}


def _validate_service(service: str) -> str:
    if not service or not _SERVICE_RE.fullmatch(service):
        raise ValueError(f"非法会话服务标识：{service!r}")
    return service


def _session_path(service: str) -> Path:
    return config_root() / "sessions" / f"{_validate_service(service)}.bin"


def _remove_legacy_files(root: Path, service: str) -> None:
    for rel in _LEGACY_REL_PATHS.get(service, ()):
        try:
            (root / rel).unlink(missing_ok=True)
        except OSError:
            pass


def _data_blob_cls():
    import ctypes
    from ctypes import wintypes

    cls = getattr(_data_blob_cls, "_cached", None)
    if cls is None:

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        cls = _DATA_BLOB
        setattr(_data_blob_cls, "_cached", cls)
    return cls


def _make_blob(raw: bytes):
    import ctypes

    blob_cls = _data_blob_cls()
    buf = (
        ctypes.create_string_buffer(raw, len(raw))
        if raw
        else ctypes.create_string_buffer(b"\x00", 1)
    )
    ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    return blob_cls, buf, blob_cls(len(raw), ptr)


def _dpapi_protect(raw: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    _DATA_BLOB, in_buf, in_blob = _make_blob(raw)
    _, ent_buf, ent_blob = _make_blob(_DPAPI_ENTROPY)
    out_blob = _DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "westlake_survival_session",
        ctypes.byref(ent_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ptr_val = ctypes.cast(out_blob.pbData, ctypes.c_void_p).value
        if ptr_val:
            kernel32.LocalFree(ptr_val)
        _ = (in_buf, ent_buf)


def _dpapi_unprotect(cipher: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    _DATA_BLOB, in_buf, in_blob = _make_blob(cipher)
    _, ent_buf, ent_blob = _make_blob(_DPAPI_ENTROPY)
    out_blob = _DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(ent_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ptr_val = ctypes.cast(out_blob.pbData, ctypes.c_void_p).value
        if ptr_val:
            kernel32.LocalFree(ptr_val)
        _ = (in_buf, ent_buf)


def _seal(raw: bytes) -> bytes:
    if os.name == "nt":
        return _DPAPI_PREFIX + _dpapi_protect(raw)
    return _PLAIN_PREFIX + raw


def _unseal(blob: bytes) -> bytes | None:
    if blob.startswith(_DPAPI_PREFIX):
        if os.name != "nt":
            return None
        try:
            return _dpapi_unprotect(blob[len(_DPAPI_PREFIX) :])
        except OSError:
            return None
    if blob.startswith(_PLAIN_PREFIX):
        return blob[len(_PLAIN_PREFIX) :]
    return None


def _atomic_write_restricted(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def save_session_data(
    service: str,
    data: dict[str, Any],
    *,
    ts: float | None = None,
) -> Path:
    """持久化指定服务的会话字典（Windows DPAPI 加密，POSIX 原子写 0600）。"""
    path = _session_path(service)
    raw = json.dumps(
        {"ts": float(ts if ts is not None else time.time()), "data": data},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    _atomic_write_restricted(path, _seal(raw))
    _remove_legacy_files(config_root(), _validate_service(service))
    return path


def load_session_data(service: str, ttl: float | None = None) -> dict[str, Any] | None:
    """读取受保护会话字典；过期/损坏/缺失返回 ``None``，并自动迁移清理历史明文文件。"""
    svc = _validate_service(service)
    root = config_root()
    path = root / "sessions" / f"{svc}.bin"

    if path.exists():
        _remove_legacy_files(root, svc)
        try:
            raw = _unseal(path.read_bytes())
        except OSError:
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        inner = payload.get("data")
        if not isinstance(inner, dict):
            return None
        if ttl is not None:
            try:
                age = time.time() - float(payload.get("ts") or 0)
            except (TypeError, ValueError):
                return None
            if age > ttl:
                return None
        return inner

    # 自动迁移历史明文 JSON 并立即删除旧文件
    for rel in _LEGACY_REL_PATHS.get(svc, ()):
        legacy = root / rel
        if not legacy.exists():
            continue
        try:
            legacy_obj = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _remove_legacy_files(root, svc)
            return None
        if not isinstance(legacy_obj, dict):
            _remove_legacy_files(root, svc)
            return None
        try:
            orig_ts = float(legacy_obj.get("ts") or legacy_obj.get("updated_at") or time.time())
        except (TypeError, ValueError):
            orig_ts = 0.0
        migrated = {k: v for k, v in legacy_obj.items() if k not in ("ts", "updated_at")}
        _remove_legacy_files(root, svc)
        if ttl is not None and (time.time() - orig_ts) > ttl:
            return None
        if migrated:
            try:
                save_session_data(svc, migrated, ts=orig_ts)
            except OSError:
                pass
            return migrated
        return None
    return None


def clear_session_data(service: str) -> None:
    """清除指定服务的会话缓存文件及历史明文遗留文件。"""
    svc = _validate_service(service)
    root = config_root()
    path = root / "sessions" / f"{svc}.bin"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    _remove_legacy_files(root, svc)
