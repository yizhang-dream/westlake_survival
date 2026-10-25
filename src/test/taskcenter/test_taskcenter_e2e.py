"""任务中心请求层端到端解析（离线，假会话返回真实响应结构）。

2026-10-25 起任务中心不再走浏览器：``_fetch_json`` 用共享会话请求
``/taskcenter/api/me/...``，本测试用假会话验证 todo/doing/done/cc/apps
四类响应都能解析，且会话失效会重登一次。

运行：``pytest src/test/taskcenter/test_taskcenter_e2e.py -q``
"""

from __future__ import annotations

import pytest

from westlake_survival import taskcenter


class _Response:
    def __init__(self, payload: dict, url: str = "https://one.westlake.edu.cn/taskcenter/api") -> None:
        self._payload = payload
        self.url = url
        self.status_code = 200
        self.text = str(payload)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        for key, payload in self.payloads.items():
            if key in url:
                return _Response(payload, url)
        return _Response({"success": True, "total": 0, "entities": []}, url)


TASK = {
    "title": "本科生社会实践申报",
    "departmentName": "学生事务部",
    "status": "审批中",
    "startDate": "2026-10-20",
    "uri": "https://one.westlake.edu.cn/infoplus/form/BKSSHSJSB/start",
}


@pytest.fixture
def fake(monkeypatch):
    session = _Session(
        {
            "tasks/todo": {"success": True, "total": 1, "entities": [TASK]},
            "processes/done": {"success": True, "total": 1, "entities": [{**TASK, "status": "已完成"}]},
            "processes/cc": {"success": True, "total": 0, "entities": []},
            "me/apps": {
                "success": True,
                "total": 1,
                "entities": [{"name": "Help Desk", "code": "XHDXXSDESK", "uri": "https://one/x"}],
            },
        }
    )
    monkeypatch.setattr(taskcenter, "_SESSION", session)
    return session


def test_todo_and_done(fake) -> None:
    todo = taskcenter.todo()
    assert len(todo) == 1
    assert todo[0].title == "本科生社会实践申报"
    assert todo[0].department == "学生事务部"
    assert todo[0].url.endswith("BKSSHSJSB/start")

    done = taskcenter.done()
    assert done[0].status == "已完成"
    # todo 带 entrust 参数，done 带分页参数
    assert any("entrust=true" in url for url in fake.calls)
    assert any("done?limit=20" in url for url in fake.calls)


def test_cc_empty_and_apps(fake) -> None:
    assert taskcenter.cc() == []
    apps = taskcenter.apps()
    assert apps == [{"name": "Help Desk", "code": "XHDXXSDESK", "uri": "https://one/x"}]


def test_session_relogin_on_redirect(monkeypatch) -> None:
    """接口把请求打回 IAM 时清会话并重登一次。"""
    class _RedirectSession(_Session):
        def __init__(self):
            super().__init__({})
            self.first = True

        def get(self, url, **kwargs):
            if self.first:
                self.first = False
                return _Response({}, "https://iam.westlake.edu.cn/ac/#/index")
            return _Response({"success": True, "total": 0, "entities": []}, url)

    session = _RedirectSession()
    monkeypatch.setattr(taskcenter, "_SESSION", session)
    assert taskcenter.todo() == []
