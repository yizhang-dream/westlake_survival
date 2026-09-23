"""``westlake cache clear`` 命令与 ``_cache.clear`` 测试。"""

from __future__ import annotations

from westlake_survival import _cache


def _seed(home) -> None:
    """在（被 WESTLAKE_HOME 重定位的）缓存目录里造几个文件。"""
    root = home / "cache"
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "transit").mkdir(parents=True, exist_ok=True)
    (root / "events" / "event_calendars.html").write_text("{}", encoding="utf-8")
    (root / "transit" / "housing_dining.html").write_text("{}", encoding="utf-8")


def test_cache_clear_all(isolated_home) -> None:
    _seed(isolated_home)
    removed = _cache.clear()
    assert removed == 2
    remaining = [p for p in _cache.cache_dir().rglob("*") if p.is_file()]
    assert remaining == []


def test_cache_clear_by_prefix(isolated_home) -> None:
    _seed(isolated_home)
    removed = _cache.clear("events")
    assert removed == 1
    remaining = {
        p.relative_to(_cache.cache_dir()).as_posix()
        for p in _cache.cache_dir().rglob("*")
        if p.is_file()
    }
    assert remaining == {"transit/housing_dining.html"}


def test_cache_clear_prefix_no_match_returns_zero(isolated_home) -> None:
    _seed(isolated_home)
    assert _cache.clear("nonexistent") == 0


def test_cache_clear_command_all(runner, cli_group, isolated_home) -> None:
    _seed(isolated_home)
    result = runner.invoke(cli_group, ["cache", "clear"])
    assert result.exit_code == 0, result.output
    assert "已清除 2 个缓存文件（全部）" in result.output


def test_cache_clear_command_module(runner, cli_group, isolated_home) -> None:
    _seed(isolated_home)
    result = runner.invoke(cli_group, ["cache", "clear", "--module", "transit"])
    assert result.exit_code == 0, result.output
    assert "已清除 1 个缓存文件（模块：transit）" in result.output
