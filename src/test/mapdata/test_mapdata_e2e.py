"""地图数据集与离线 POI 的端到端测试。

真实验证链：临时目录里构造抓取原始件 → 跑 ``tools/build_map_dataset.py``
生成数据集 → 用 ``WESTLAKE_MAP_DATASET`` 指向它 → 跑 ``westlake map poi``
真实 CLI，核对输出命中。

运行：``pytest src/test/mapdata/test_mapdata_e2e.py -q``（无需网络）
与 ``pytest src/test/mapdata/test_mapdata_e2e.py -q -m live``（含真实缺失路径）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from westlake_survival import mapdata
from westlake_survival.campusmap import cli_group

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_TOOL = REPO_ROOT / "tools" / "build_map_dataset.py"


def test_poi_without_dataset_prints_capture_guidance(tmp_path, monkeypatch) -> None:
    """数据集缺位时给出可执行指引，而不是报错。"""
    monkeypatch.setenv("WESTLAKE_MAP_DATASET", str(tmp_path / "missing.json"))

    result = CliRunner().invoke(cli_group, ["poi", "图书馆"])

    assert result.exit_code == 0, result.output
    assert "尚未生成" in result.output
    assert "capture_map.py" in result.output


def test_build_then_query_real_pipeline(tmp_path, monkeypatch) -> None:
    """真实管线：原始抓取件 → build 脚本 → 数据集 → CLI 检索命中。"""
    raw = {
        "captured_at": "2026-10-23T17:00:00",
        "source": "https://map.westlake.edu.cn",
        "endpoints": {
            "/api/nsc/map/poi/list": [
                {"name": "图书馆", "floorName": "1F", "buildingName": "学术环"},
                {"name": "图书馆", "floorName": "1F", "buildingName": "学术环"},  # 重复项应被去重
                {"name": "云谷食堂", "floorName": "2F"},
                {"unrelated": "无名称字段，应被丢弃"},
            ],
            "/api/nsc/uc/ndConfig/findNdConfigListByKeys": [
                {"name": "配置项不应进入数据集"},
            ],
        },
    }
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    dataset_path = tmp_path / "campus_map.json"

    build = subprocess.run(
        [sys.executable, str(BUILD_TOOL), str(raw_path), "--out", str(dataset_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert build.returncode == 0, build.stderr
    assert dataset_path.exists()

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert "ndConfig" not in " ".join(dataset["endpoints"])
    assert len(dataset["endpoints"]["/api/nsc/map/poi/list"]) == 2  # 去重 + 丢弃无名项

    monkeypatch.setenv("WESTLAKE_MAP_DATASET", str(dataset_path))
    result = CliRunner().invoke(cli_group, ["poi", "图书馆"])

    assert result.exit_code == 0, result.output
    assert "图书馆" in result.output
    assert "学术环" in result.output
    assert "云谷食堂" not in result.output  # 关键词过滤生效


def test_dataset_missing_raises_filenotfound(tmp_path, monkeypatch) -> None:
    """底层 API 在缺文件时抛 FileNotFoundError，便于调用方区分「未生成」。"""
    monkeypatch.setenv("WESTLAKE_MAP_DATASET", str(tmp_path / "nope.json"))

    assert not mapdata.dataset_available()
    try:
        mapdata.load_dataset()
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("应当抛 FileNotFoundError")
