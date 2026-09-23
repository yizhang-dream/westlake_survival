"""``westlake_survival.webui`` —— 本地 Web 界面。

一个进程内 Flask 应用，默认绑定 ``127.0.0.1:2018``（2018 = 西湖大学建校年）。
提供「信息仪表盘」风格的页面：

* ``/``          —— context 快照仪表盘（日期 / 周次 / 最近事件 / 下班车 / 天气）
* ``/shuttle``   —— 各校区班车时刻表 + 「现在出发」高亮
* ``/calendar``  —— 本学期校历事件 + 周次进度
* ``/api/*``     —— 同名数据的 JSON 版本
* ``/ical/*``    —— 班车 / 课表 ``.ics`` 下载

设计取舍（v1 简化）：

* 单内置模板，不做皮肤系统（对标 sustech_survival 的多皮肤是后续版本的事）。
* CSS 直接内联在 ``base.html``，不设 ``static/`` 目录。
* 不引入前端框架，不提供登录 / 鉴权——本地工具，只绑 ``127.0.0.1``。
* 各依赖模块（``context`` / ``sis`` / ``ical``）**惰性导入**：模块缺失或数据
  不可用时优雅降级（卡片显示 ``—``、页面仍为 200），不因某一数据源而 500。

公开 API::

    from westlake_survival.webui import create_app, run

    app = create_app()      # Flask app factory（测试 / WSGI 部署用）
    run()                   # 起本地服务并打印访问地址
"""

from __future__ import annotations

from westlake_survival.webui.app import create_app, run

__all__ = ["create_app", "run"]
