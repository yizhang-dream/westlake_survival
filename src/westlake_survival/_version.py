"""版本定义与发布身份元数据。

遵循语义化版本规范（SemVer 2.0.0），参考 archify 的版本体系设计。
作为全项目单一真实来源（Single Source of Truth），供 pyproject.toml、
CLI、WebUI、MCP 以及发布契约模块统一读取。
"""

from __future__ import annotations

import re
from typing import NamedTuple

__version__ = "1.0.0"

#: 发布日期（ISO-8601）
__release_date__ = "2026-11-02"

#: 默认发布渠道：stable（稳定版）或 development（预发布/开发版）
__channel__ = "stable"


class VersionInfo(NamedTuple):
    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None


def parse_version_info(version_str: str = __version__) -> VersionInfo:
    """将版本字符串解析为结构化 VersionInfo。"""
    match = re.match(
        r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$",
        version_str,
    )
    if not match:
        return VersionInfo(major=1, minor=0, patch=0)
    major, minor, patch, prerelease, build = match.groups()
    return VersionInfo(
        major=int(major),
        minor=int(minor),
        patch=int(patch),
        prerelease=prerelease,
        build=build,
    )


VERSION_INFO = parse_version_info(__version__)
