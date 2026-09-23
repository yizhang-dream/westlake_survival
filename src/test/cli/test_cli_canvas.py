"""``westlake canvas`` 命令测试：无 token 的 AuthError 提示 + 成功路径。"""

from __future__ import annotations

from datetime import datetime

from westlake_survival.exceptions import AuthError, OffCampusError


def test_canvas_courses_without_token(runner, cli_group, isolated_home) -> None:
    """无 token 时应给令牌获取引导并以退出码 1 结束。"""
    result = runner.invoke(cli_group, ["canvas", "courses"])
    assert result.exit_code == 1
    assert "错误" in result.stderr
    assert "新建访问令牌" in result.stderr
    assert "WESTLAKE_CANVAS_TOKEN" in result.stderr


def test_canvas_deadlines_without_token(runner, cli_group, isolated_home) -> None:
    result = runner.invoke(cli_group, ["canvas", "deadlines"])
    assert result.exit_code == 1
    assert "新建访问令牌" in result.stderr


def test_canvas_courses_success(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.canvas as canvas_pkg

    class FakeCourse:
        course_code = "CS101"
        name = "计算机导论"
        term_name = "2026年秋季"

    class FakeClient:
        def list_courses(self):
            return [FakeCourse()]

    monkeypatch.setattr(canvas_pkg, "canvas", lambda token=None: FakeClient())
    result = runner.invoke(cli_group, ["canvas", "courses"])
    assert result.exit_code == 0
    assert "CS101" in result.output
    assert "计算机导论" in result.output


def test_canvas_deadlines_success(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.canvas as canvas_pkg

    class FakeAssignment:
        due_at = datetime(2026, 9, 30, 23, 59)
        name = "作业一"
        html_url = "https://canvas.example/1"

    class FakeClient:
        def upcoming_deadlines(self, limit=10):
            assert limit == 2
            return [FakeAssignment()]

    monkeypatch.setattr(canvas_pkg, "canvas", lambda token=None: FakeClient())
    result = runner.invoke(cli_group, ["canvas", "deadlines", "--limit", "2"])
    assert result.exit_code == 0
    assert "2026-09-30" in result.output
    assert "作业一" in result.output


def test_canvas_generic_westlake_error(runner, cli_group, monkeypatch) -> None:
    import westlake_survival.canvas as canvas_pkg

    def boom(token=None):
        raise OffCampusError("仅校园网可达")

    monkeypatch.setattr(canvas_pkg, "canvas", boom)
    result = runner.invoke(cli_group, ["canvas", "courses"])
    assert result.exit_code == 1
    assert "vpn.westlake.edu.cn" in result.stderr


def test_canvas_auth_error_kind(runner, cli_group, monkeypatch) -> None:
    """AuthError 走 canvas 专用分支（含令牌引导）。"""
    import westlake_survival.canvas as canvas_pkg

    def boom(token=None):
        raise AuthError("无 token")

    monkeypatch.setattr(canvas_pkg, "canvas", boom)
    result = runner.invoke(cli_group, ["canvas", "courses"])
    assert result.exit_code == 1
    assert "新建访问令牌" in result.stderr
