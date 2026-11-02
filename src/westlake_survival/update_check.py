"""版本更新感知与检查模块（Update Awareness）。

参考 archify 的 update-awareness 协议与 check-update 机制设计：
1. 非阻塞与缓存化：本地缓存检查结果（TTL 24 小时），离线或网络故障静默降级，不阻塞业务；
2. 尊重用户控制权：通知是信息，绝非权限；绝不后台自动下载、静默覆盖或强行升级；
3. 免打扰管理：支持 snooze（推迟 7 天提醒）与 ignore（忽略特定版本）。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

from westlake_survival._version import __version__
from westlake_survival.version_contract import (
    DEFAULT_MANIFEST_URL,
    compare_semver,
    load_local_release,
    parse_semver,
)

CACHE_FILENAME = "update_cache.json"
CACHE_TTL_SECONDS = 86400  # 24 小时


@dataclass
class UpdateCheckResult:
    """更新检查返回结果。"""

    current_version: str
    latest_version: str | None = None
    has_update: bool = False
    source: str = "network"  # "network" | "cache" | "offline"
    checked_at: str = ""
    summary: str = ""
    release_notes: str = ""
    snoozed: bool = False
    ignored: bool = False
    notice_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_cache_path() -> str:
    from westlake_survival._cache import config_root

    return str(config_root() / CACHE_FILENAME)


def _load_cache() -> dict[str, Any]:
    path = _get_cache_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(data: dict[str, Any]) -> None:
    path = _get_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def snooze_update(version: str, days: int = 7) -> None:
    """暂停指定版本的更新提示 N 天（默认 7 天）。"""
    cache = _load_cache()
    snooze_until = int(time.time()) + (days * 86400)
    cache.setdefault("snoozed", {})[version] = snooze_until
    _save_cache(cache)


def ignore_update(version: str) -> None:
    """永久忽略指定版本的更新提示。"""
    cache = _load_cache()
    ignored = set(cache.get("ignored", []))
    ignored.add(version)
    cache["ignored"] = list(ignored)
    _save_cache(cache)


def check_for_updates(
    force_network: bool = False,
    timeout: float = 2.0,
) -> UpdateCheckResult:
    """检查是否有新版本可用。

    先检查本地缓存，若未过期直接使用缓存数据；
    若需刷新，则拉取远程 skill-release.json 或 GitHub Release 清单。
    网络异常时自动安全降级，不阻塞主流程。
    """
    local_info = load_local_release()
    curr_v = local_info.get("version", __version__)
    cache = _load_cache()
    now = int(time.time())

    # 1. 命中缓存
    cached_check = cache.get("last_check")
    if (
        not force_network
        and cached_check
        and (now - cached_check.get("timestamp", 0) < CACHE_TTL_SECONDS)
    ):
        latest_v = cached_check.get("latest_version")
        if latest_v:
            return _evaluate_update(curr_v, latest_v, cached_check, cache, source="cache")

    # 2. 线上网络探测（轻量快速超时）
    manifest_url = local_info.get("updateManifestUrl", DEFAULT_MANIFEST_URL)
    remote_data: dict[str, Any] = {}
    try:
        import urllib.request

        req = urllib.request.Request(
            manifest_url,
            headers={"User-Agent": f"westlake-survival/{curr_v}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                remote_data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # 网络异常时静默降级，检查是否有旧缓存可用
        if cached_check:
            latest_v = cached_check.get("latest_version")
            if latest_v:
                return _evaluate_update(curr_v, latest_v, cached_check, cache, source="cache")
        return UpdateCheckResult(
            current_version=curr_v,
            has_update=False,
            source="offline",
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        )

    latest_v = remote_data.get("version")
    if not latest_v:
        return UpdateCheckResult(
            current_version=curr_v,
            has_update=False,
            source="network",
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        )

    # 更新缓存
    record = {
        "timestamp": now,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "latest_version": latest_v,
        "summary": remote_data.get("summary", ""),
        "release_notes": remote_data.get(
            "releaseNotes",
            f"https://github.com/yizhang-dream/westlake_survival/releases/tag/v{latest_v}",
        ),
    }
    cache["last_check"] = record
    _save_cache(cache)

    return _evaluate_update(curr_v, latest_v, record, cache, source="network")


def _evaluate_update(
    curr_v: str,
    latest_v: str,
    record: dict[str, Any],
    cache: dict[str, Any],
    source: str,
) -> UpdateCheckResult:
    now = int(time.time())
    try:
        has_update = compare_semver(curr_v, latest_v) < 0
    except Exception:
        has_update = False

    snoozed_dict = cache.get("snoozed", {})
    snooze_until = snoozed_dict.get(latest_v, 0)
    is_snoozed = now < snooze_until

    ignored_list = cache.get("ignored", [])
    is_ignored = latest_v in ignored_list

    notice = ""
    if has_update and not is_snoozed and not is_ignored:
        notes_url = record.get("release_notes", "")
        notice = (
            f"💡 发现新版本 westlake_survival {latest_v}（当前已装 {curr_v}）\n"
            f"   更新说明: {notes_url}\n"
            f"   升级命令: pip install --upgrade westlake-survival\n"
            f"   若需推迟提醒可执行: westlake update-snooze"
        )

    return UpdateCheckResult(
        current_version=curr_v,
        latest_version=latest_v,
        has_update=has_update,
        source=source,
        checked_at=record.get("checked_at", ""),
        summary=record.get("summary", ""),
        release_notes=record.get("release_notes", ""),
        snoozed=is_snoozed,
        ignored=is_ignored,
        notice_text=notice,
    )
