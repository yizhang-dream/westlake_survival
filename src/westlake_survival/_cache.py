"""配置目录与 JSON 缓存、ETag 条件请求。

约定（与 sustech_survival 一致）：
- 凭据与会话 **只存在内存**，绝不落盘；本模块只缓存公开数据
  （校历、班车时刻表、API 响应缓存）。
- 根目录默认 ``~/.westlake_survival``，可用环境变量
  ``WESTLAKE_HOME`` 重定位（测试用）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from westlake_survival._net import http_session


def config_root() -> Path:
    """返回配置根目录（不存在则创建）。"""
    override = os.environ.get("WESTLAKE_HOME")
    root = Path(override).expanduser() if override else Path.home() / ".westlake_survival"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir() -> Path:
    """返回缓存目录（不存在则创建）。"""
    path = config_root() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(name: str) -> Path:
    """缓存文件的完整路径；``name`` 可含子目录（会自动创建）。"""
    path = cache_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_json(name: str, obj: Any) -> Path:
    """把可 JSON 序列化对象写入缓存文件。"""
    path = cache_path(name)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_json(name: str, default: Any = None) -> Any:
    """读取缓存 JSON；不存在或损坏时返回 *default*。"""
    path = cache_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def load_cached(name: str, ttl: float, default: Any = None) -> Any:
    """读取带时间戳的缓存；超过 *ttl* 秒或格式不符时返回 *default*。"""
    payload = load_json(name)
    if not isinstance(payload, dict) or "ts" not in payload:
        return default
    try:
        if time.time() - float(payload["ts"]) > ttl:
            return default
    except (TypeError, ValueError):
        return default
    return payload.get("data", default)


def save_cached(name: str, data: Any) -> Path:
    """写入带时间戳的缓存（配合 :func:`load_cached` 使用）。"""
    return save_json(name, {"ts": time.time(), "data": data})


def snapshots_dir() -> Path:
    """返回持久化业务快照目录（离线优先，不随简单 cache clear 轻易抹除）。"""
    path = config_root() / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_snapshot(namespace: str, key: str, data: Any) -> Path:
    """保存业务数据快照（含时间戳与版本）。"""
    clean_ns = namespace.strip("/\\")
    clean_k = key.strip("/\\")
    path = snapshots_dir() / clean_ns / f"{clean_k}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": time.time(),
        "namespace": namespace,
        "key": key,
        "data": data,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(namespace: str, key: str) -> tuple[Any, float | None]:
    """读取业务数据快照。返回 (data, saved_timestamp)；不存在或损坏返回 (None, None)。"""
    clean_ns = namespace.strip("/\\")
    clean_k = key.strip("/\\")
    path = snapshots_dir() / clean_ns / f"{clean_k}.json"
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data"), float(payload.get("ts") or 0)
    except Exception:
        pass
    return None, None


def fetch_with_swr(
    namespace: str,
    key: str,
    fetcher: Any,
    *,
    offline: bool = False,
    max_stale_age: float = 86400 * 30,
) -> tuple[Any, dict[str, Any]]:
    """Stale-While-Revalidate（离线优先与快照优雅降级）。

    Args:
        namespace: 业务命名空间（如 "schedule", "calendar", "transit"）
        key: 快照键（如 "current", "terms", "bus_table"）
        fetcher: 实时拉取函数
        offline: 显式离线模式（直接使用本地快照，不发网络请求）
        max_stale_age: 允许的最大过期时长（秒，默认 30 天）

    Returns:
        (data, meta_info_dict)
    """
    from datetime import datetime

    if offline:
        data, ts = load_snapshot(namespace, key)
        if data is not None:
            ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "未知"
            return data, {
                "source": "offline_snapshot",
                "is_stale": True,
                "snapshot_time": ts,
                "snapshot_time_str": ts_str,
            }
        from westlake_survival.exceptions import WestlakeError

        raise WestlakeError(
            f"离线模式下未找到 [{namespace}/{key}] 的本地快照，请先在联网环境下运行一次以建立快照。"
        )

    # 尝试联网获取
    try:
        live_data = fetcher()
        # 序列化友好检查或转换
        serializable = live_data
        if hasattr(live_data, "to_dict"):
            serializable = live_data.to_dict()
        elif isinstance(live_data, list) and live_data and hasattr(live_data[0], "to_dict"):
            serializable = [item.to_dict() for item in live_data]
        elif isinstance(live_data, (dict, list, str, int, float, bool)) or live_data is None:
            serializable = live_data

        try:
            save_snapshot(namespace, key, serializable)
        except Exception:
            pass

        now_ts = time.time()
        now_str = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M")
        return live_data, {
            "source": "live",
            "is_stale": False,
            "snapshot_time": now_ts,
            "snapshot_time_str": now_str,
        }
    except Exception as exc:
        # 网络异常，尝试回退到本地快照
        data, ts = load_snapshot(namespace, key)
        if data is not None and (ts is None or (time.time() - ts) <= max_stale_age):
            ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "未知"
            return data, {
                "source": "stale_snapshot",
                "is_stale": True,
                "snapshot_time": ts,
                "snapshot_time_str": ts_str,
                "fallback_reason": str(exc),
            }
        raise


def clear(prefix: str | None = None) -> int:
    """删除缓存文件（可选只删某个模块/前缀），返回删除的文件数。

    Args:
        prefix: 相对缓存目录的路径前缀，如 ``"events"``（清掉
            ``events/event_calendars.html``）或 ``"calendar/academic_calendar.html"``；
            ``None`` 表示清空整个缓存目录。

    Returns:
        实际删除的文件数。单个文件删不掉（被占用等）时跳过并继续，绝不抛异常；
        随后尽力清理空目录。
    """
    root = cache_dir()
    token = (prefix or "").strip().strip("/\\")
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if token and not relative.startswith(token):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:  # 文件被占用 / 权限不足：跳过，不阻断其余清理
            continue
    # 尽力回收空目录（由深到浅，rmdir 失败即忽略）。
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            path.rmdir()  # 非空会抛 OSError
        except OSError:
            continue
    return removed


def http_get_with_etag(
    url: str,
    *,
    cache_name: str,
    session: requests.Session | None = None,
    timeout: float = 15.0,
) -> tuple[str, str | None]:
    """带 ETag 条件请求的 GET，响应体本地缓存。

    Returns:
        ``(body_text, etag)`` —— 服务器返回 304 时给缓存内容。
    """
    session = session or http_session()
    cached = load_json(cache_name, default=None) or {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}
    response = session.get(url, headers=headers, timeout=timeout)
    if response.status_code == 304 and cached.get("body"):
        return cached["body"], cached.get("etag")
    response.raise_for_status()
    etag = response.headers.get("ETag") or cached.get("etag")
    body = _decoded_text(response)
    if etag:
        save_json(cache_name, {"etag": etag, "body": body})
    return body, etag


def _decoded_text(response: requests.Response) -> str:
    """取响应文本，修复"无 charset 头被当 ISO-8859-1"的中文乱码。

    西湖官网多数页面是 UTF-8 但不带 charset 声明，requests 会按
    ISO-8859-1 解码出乱码；此处在该场景下改用探测编码重新解码。
    """
    encoding = (response.encoding or "").lower()
    if encoding in ("", "iso-8859-1", "latin-1"):
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text
