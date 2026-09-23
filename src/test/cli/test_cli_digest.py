"""``westlake digest`` 命令测试（组合、降级、Canvas token 条件并入）。"""

from __future__ import annotations

from westlake_survival.cli import main as main_mod


def _stub_sources(monkeypatch, *, overview=None, events=None, shuttle=None, week=None, canvas=None):
    """把 digest 各数据源替换为返回固定行的桩函数。"""
    monkeypatch.setattr(main_mod, "_digest_overview", overview or (lambda: ["概览固定行"]))
    monkeypatch.setattr(main_mod, "_digest_events", events or (lambda: ["- 活动固定行"]))
    monkeypatch.setattr(main_mod, "_digest_shuttle", shuttle or (lambda: ["- 班车固定行"]))
    monkeypatch.setattr(main_mod, "_digest_week", week or (lambda: ["- 周次固定行"]))
    monkeypatch.setattr(main_mod, "_digest_canvas", canvas or (lambda: ["- Canvas 固定行"]))


def test_digest_normal_combines_all_sources(runner, cli_group, monkeypatch) -> None:
    """normal 档应包含概览 / 活动 / 班车 / 周次 / Canvas 五节。"""
    _stub_sources(monkeypatch)
    result = runner.invoke(cli_group, ["digest"])
    assert result.exit_code == 0, result.output
    assert "西湖大学晨报" in result.output
    for section in ("## 概览", "## 今日 / 明日活动", "## 下一班校车", "## 本周次", "## Canvas 截止"):
        assert section in result.output
    for line in ("概览固定行", "活动固定行", "班车固定行", "周次固定行", "Canvas 固定行"):
        assert line in result.output


def test_digest_terse_omits_network_sections(runner, cli_group, monkeypatch) -> None:
    """terse 档只保留概览与周次，活动 / 班车 / Canvas 不应被调用。"""
    called: list[str] = []
    monkeypatch.setattr(main_mod, "_digest_overview", lambda: ["概览固定行"])
    monkeypatch.setattr(main_mod, "_digest_week", lambda: ["- 周次固定行"])

    def _boom(name):
        def inner():
            called.append(name)
            return ["不应出现"]

        return inner

    monkeypatch.setattr(main_mod, "_digest_events", _boom("events"))
    monkeypatch.setattr(main_mod, "_digest_shuttle", _boom("shuttle"))
    monkeypatch.setattr(main_mod, "_digest_canvas", _boom("canvas"))

    result = runner.invoke(cli_group, ["digest", "--level", "terse"])
    assert result.exit_code == 0, result.output
    assert "## 概览" in result.output
    assert "## 本周次" in result.output
    assert "## 今日 / 明日活动" not in result.output
    assert "## 下一班校车" not in result.output
    assert "## Canvas 截止" not in result.output
    assert called == []


def test_digest_source_failure_degrades_to_placeholder(runner, cli_group, monkeypatch) -> None:
    """单个数据源抛异常：该节降级为占位行（附异常类名），其余节仍渲染。"""
    def boom():
        raise RuntimeError("上游炸了")

    _stub_sources(monkeypatch, events=boom)
    result = runner.invoke(cli_group, ["digest"])
    assert result.exit_code == 0, result.output
    assert "（暂不可用）（RuntimeError）" in result.output
    assert "班车固定行" in result.output  # 其余节不受影响


def test_digest_invalid_level_rejected(runner, cli_group) -> None:
    result = runner.invoke(cli_group, ["digest", "--level", "verbose"])
    assert result.exit_code != 0


def test_digest_canvas_included_when_token_env_set(runner, cli_group, monkeypatch) -> None:
    """设置了 WESTLAKE_CANVAS_TOKEN 时应并入 Canvas 截止（真实 _digest_canvas 路径）。"""
    import westlake_survival.canvas as canvas_pkg

    class FakeAssignment:
        name = "大作业"
        due_at = None

    class FakeClient:
        def upcoming_deadlines(self, limit=10):
            return [FakeAssignment()]

    monkeypatch.setenv("WESTLAKE_CANVAS_TOKEN", "dummy-token")
    monkeypatch.setattr(canvas_pkg, "canvas", lambda *a, **k: FakeClient())
    result = runner.invoke(cli_group, ["digest"])
    assert result.exit_code == 0, result.output
    assert "大作业" in result.output


def test_digest_canvas_skipped_without_token(runner, cli_group, monkeypatch) -> None:
    """无 token 时 Canvas 节显示跳过说明，而不是报错。"""
    monkeypatch.delenv("WESTLAKE_CANVAS_TOKEN", raising=False)
    result = runner.invoke(cli_group, ["digest"])
    assert result.exit_code == 0, result.output
    assert "未配置" in result.output
    assert "跳过 Canvas 截止" in result.output
