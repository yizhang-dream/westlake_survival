"""src/test/lib 共用的离线 mock 与 fixture 构造。

响应结构按 2026-09-22 实测校准：

- OPAC 结果页类名（取自站点 ``jishen.css``）：``.book-list`` / ``.book-fld`` /
  ``.book-fld-title`` / ``.book-fld-other`` / ``.booktable`` / ``.hld-list-header``。
- 门户 JSON 信封（实测 ``POST /bolan-newbook/api/newbook/tenantRule``）：
  ``{"code":200,"returnflag":true,"message":"请求成功","data":...}``；
  未登录为 ``{"success":false,"code":"UNAUTHORIZED","message":"需要先登录"}``。
"""

from __future__ import annotations

import json
from typing import Any


class FakeResponse:
    """最小化的 requests.Response 替身。"""

    def __init__(
        self,
        body: bytes | str = b"",
        *,
        status: int = 200,
        encoding: str = "utf-8",
        url: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(body, str):
            body = body.encode(encoding)
        self.content = body
        self.status_code = status
        self.encoding = encoding
        self.apparent_encoding = "utf-8"
        self.url = url
        self.headers = headers or {}

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding or "utf-8", errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class FakeSession:
    """记录调用并按 responder 返回响应的 session 替身。"""

    def __init__(self, response: FakeResponse | None = None, responder=None) -> None:
        self._response = response
        self._responder = responder
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("post", url, kwargs))
        return self._resolve(url)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("get", url, kwargs))
        return self._resolve(url)

    def _resolve(self, url: str) -> FakeResponse:
        if self._responder is not None:
            return self._responder(url)
        assert self._response is not None
        return self._response


class FakeAuth:
    """LibAuth 替身：按 URL 返回响应。"""

    def __init__(self, responder) -> None:
        self._responder = responder
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(url)
        return self._responder(url)


# --------------------------------------------------------------------------- #
# Fixture 内容
# --------------------------------------------------------------------------- #

#: 两条书目；字段以全角冒号分隔，与阿法迪 OPAC 结果行一致。
BOOKLIST_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>检索结果</title></head>
<body>
<div class="search-info">共 2 条记录</div>
<div class="book-list">
  <div class="book-fld">
    <div class="book-fld-title"><a href="/opac/bookdetail.jsp?bookid=1001">机器学习</a></div>
    <div class="book-fld-other">作者：周志华 出版社：清华大学出版社 出版年：2016 索书号：TP181/Z68 ISBN：978-7-302-42328-7 馆藏地：云谷校区</div>
  </div>
</div>
<div class="book-list">
  <div class="book-fld">
    <div class="book-fld-title"><a href="/opac/bookdetail.jsp?bookid=1002">深度学习</a></div>
    <div class="book-fld-other">作者：Ian Goodfellow 出版社：人民邮电出版社 出版年：2017 索书号：TP181/G66 ISBN：978-7-115-46147-6 馆藏地：云栖校区</div>
  </div>
</div>
</body></html>
"""

BOOKLIST_HTML_GBK = """<!DOCTYPE html>
<html><head><meta charset="gb2312"><title>检索结果</title></head>
<body>
<div class="book-list">
  <div class="book-fld">
    <div class="book-fld-title"><a href="/opac/bookdetail.jsp?bookid=2001">数据库系统概论</a></div>
    <div class="book-fld-other">作者：王珊 出版社：高等教育出版社 出版年：2014 索书号：TP311.13/W36 ISBN：978-7-04-040664-1 馆藏地：云谷校区</div>
  </div>
</div>
</body></html>
"""

BOOK_DETAIL_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<h2 class="detail-title">机器学习</h2>
<table>
  <tr><th>馆藏地</th><th>索书号</th><th>状态</th></tr>
  <tr><td>云谷校区</td><td>TP181/Z68</td><td>在馆</td></tr>
  <tr><td>云栖校区</td><td>TP181/Z68</td><td>借出</td></tr>
</table>
</body></html>
"""

NEW_BOOKS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<div class="book-list">
  <div class="book-fld">
    <div class="book-fld-title"><a href="/opac/bookdetail.jsp?bookid=3001">人工智能导论</a></div>
    <div class="book-fld-other">作者：李德毅 出版社：科学出版社 出版年：2021 索书号：TP18/L31 ISBN：978-7-03-068901-2 馆藏地：云谷校区</div>
  </div>
</div>
</body></html>
"""

LOANS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<h3>当前借阅</h3>
<table class="loan-list">
  <tr><th>题名</th><th>条码号</th><th>应还日期</th><th>续借</th><th>馆藏地</th></tr>
  <tr><td>机器学习</td><td>B1001</td><td>2026-10-01</td><td>可续借</td><td>云谷校区</td></tr>
  <tr><td>深度学习</td><td>B1002</td><td>2026-10-05</td><td>不可续借</td><td>云栖校区</td></tr>
</table>
</body></html>
"""

LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body><form action="/login">
  <input type="text" name="username">
  <input type="password" name="password">
  <button type="submit">登录</button>
</form></body></html>
"""

#: 普通页面：带“修改密码 password”链接 + “登录”导航词，但**无密码输入框**。
#: reviewer 实测的误判样本（旧规则会因 password + 登录 共现判为登录页）。
PLAIN_PAGE_WITH_PASSWORD_LINK_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<h1>图书馆公告</h1>
<p>关于假期开放时间的通知。请通过统一身份认证登录后使用个人服务。</p>
<a href="/opac/reader/changePassword.do">修改密码 password</a>
</body></html>
"""

#: 纯中文登录页：可见文本全中文（标题“用户认证”、按钮“提交”），正文没有
#: ``login`` / ``登录`` 字样。旧子串规则因缺 ``login|登录`` 而漏判为 False；
#: 新规则靠“``<form>`` 内含 ``type=password`` 输入”判 True。
CN_LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body><form action="/auth">
  <h2>用户认证</h2>
  <input type="text" name="username" placeholder="用户名">
  <input type="password" name="pwd">
  <button type="submit">提交</button>
</form></body></html>
"""

CATALOG_SEARCH_JSON = json.dumps(
    {
        "code": 200,
        "returnflag": True,
        "message": "请求成功",
        "data": {
            "list": [
                {
                    "id": 1001,
                    "title": "机器学习",
                    "author": "周志华",
                    "publisher": "清华大学出版社",
                    "publishdate": "2016",
                    "isbn": "978-7-302-42328-7",
                    "callnumber": "TP181/Z68",
                    "location": "云谷校区",
                    "status": "在馆",
                }
            ]
        },
    },
    ensure_ascii=False,
)

CATALOG_UNAUTHORIZED_JSON = json.dumps(
    {"success": False, "code": "UNAUTHORIZED", "message": "需要先登录"},
    ensure_ascii=False,
)

OFFCAMPUS_HTML = "Access forbidden, please contact administrator"