"""版本契约规范与校验（Version & Update Contract）。

参考 archify 的 update-contract 规范设计，定义语义化版本（SemVer 2.0.0）
解析、版本比较、发行频道判定以及本地发行元数据清单（skill-release.json）
与远程更新清单的严格结构化校验。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

SKILL_ID = "westlake-survival"
EXPECTED_REPOSITORY = "https://github.com/yizhang-dream/westlake_survival"
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/yizhang-dream/westlake_survival/main/skill-release.json"
)

SEMVER_REGEX = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class UpdateContractError(ValueError):
    """版本契约与校验异常。"""


@dataclass(frozen=True)
class SemVerParts:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] | None = None
    build: tuple[str, ...] | None = None


def parse_semver(value: str) -> SemVerParts:
    """严格解析符合 SemVer 2.0.0 规范的版本字符串。"""
    if not isinstance(value, str) or len(value) > 128:
        raise UpdateContractError(f"版本号格式无效: {value!r}")
    match = SEMVER_REGEX.match(value.strip())
    if not match:
        raise UpdateContractError(f"版本号不符合 SemVer 2.0.0 规范: {value!r}")

    major_s, minor_s, patch_s, pre_s, build_s = match.groups()
    prerelease = tuple(pre_s.split(".")) if pre_s else None
    if prerelease:
        for ident in prerelease:
            if ident.isdigit() and len(ident) > 1 and ident.startswith("0"):
                raise UpdateContractError(f"SemVer 预发布标识段不能包含前导零: {ident!r}")

    build = tuple(build_s.split(".")) if build_s else None
    return SemVerParts(
        major=int(major_s),
        minor=int(minor_s),
        patch=int(patch_s),
        prerelease=prerelease,
        build=build,
    )


def compare_semver(left_str: str, right_str: str) -> int:
    """比较两个 SemVer 2.0.0 版本号。

    返回值：
      -1: left < right
       0: left == right
       1: left > right
    """
    left = parse_semver(left_str)
    right = parse_semver(right_str)

    # 1. 核心版本三元组比较
    for l_val, r_val in (
        (left.major, right.major),
        (left.minor, right.minor),
        (left.patch, right.patch),
    ):
        if l_val < r_val:
            return -1
        if l_val > r_val:
            return 1

    # 2. 预发布版本段比较（无预发布标识 > 有预发布标识，如 1.0.0 > 1.0.0-rc.1）
    if left.prerelease is None and right.prerelease is None:
        return 0
    if left.prerelease is None:
        return 1
    if right.prerelease is None:
        return -1

    max_len = max(len(left.prerelease), len(right.prerelease))
    for i in range(max_len):
        if i >= len(left.prerelease):
            return -1
        if i >= len(right.prerelease):
            return 1
        l_part = left.prerelease[i]
        r_part = right.prerelease[i]
        if l_part == r_part:
            continue

        l_is_num = l_part.isdigit()
        r_is_num = r_part.isdigit()
        if l_is_num and r_is_num:
            l_num, r_num = int(l_part), int(r_part)
            if l_num != r_num:
                return -1 if l_num < r_num else 1
        elif l_is_num != r_is_num:
            return -1 if l_is_num else 1
        else:
            return -1 if l_part < r_part else 1

    return 0


def release_channel_for_version(value: str) -> str:
    """根据版本是否包含预发布段判定发行渠道（stable vs development）。"""
    parts = parse_semver(value)
    return "development" if parts.prerelease else "stable"


def validate_local_release(data: Mapping[str, Any]) -> dict[str, Any]:
    """校验本地 skill-release.json 结构合法性。"""
    required_keys = {"schemaVersion", "skillId", "channel", "version", "source", "updateManifestUrl"}
    if not required_keys.issubset(data.keys()):
        missing = required_keys - set(data.keys())
        raise UpdateContractError(f"skill-release.json 缺少必要字段: {missing}")

    if data["schemaVersion"] != 1:
        raise UpdateContractError(f"不支持的 schemaVersion: {data['schemaVersion']}")

    if data["skillId"] != SKILL_ID:
        raise UpdateContractError(f"skillId 不匹配: 预期 {SKILL_ID}, 实际 {data['skillId']}")

    version = str(data["version"])
    expected_channel = release_channel_for_version(version)
    if data["channel"] != expected_channel:
        raise UpdateContractError(
            f"发行渠道与版本号不匹配: 声明 {data['channel']!r}, 判定 {expected_channel!r}"
        )

    source = data.get("source")
    if not isinstance(source, dict) or source.get("repository") != EXPECTED_REPOSITORY:
        raise UpdateContractError(f"source.repository 不匹配: 预期 {EXPECTED_REPOSITORY}")

    return dict(data)


def load_local_release(path: str | None = None) -> dict[str, Any]:
    """读取并校验本地 skill-release.json。若不存在则回退至 _version.py 构建。"""
    if path is None:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        # 依次尝试根目录与包目录
        candidate_roots = [
            os.path.abspath(os.path.join(cur_dir, "..", "..")),
            cur_dir,
        ]
        for root in candidate_roots:
            p = os.path.join(root, "skill-release.json")
            if os.path.isfile(p):
                path = p
                break

    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return validate_local_release(data)

    from westlake_survival._version import __channel__, __version__

    fallback = {
        "schemaVersion": 1,
        "skillId": SKILL_ID,
        "channel": __channel__,
        "version": __version__,
        "source": {"repository": EXPECTED_REPOSITORY},
        "updateManifestUrl": DEFAULT_MANIFEST_URL,
    }
    return validate_local_release(fallback)
