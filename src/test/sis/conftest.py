"""src/test/sis 的公共夹具：假 HTTP 层 + 单例/缓存清理 + fixture 路径。

所有测试**离线**：不发起任何真实网络请求（live 测试除外，默认被
``-m 'not live'`` 排除）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from westlake_survival.sis import reset_sis

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, tmp_path):
    """每个测试前：清空客户端单例、重定位配置/缓存目录到 tmp。"""
    reset_sis()
    monkeypatch.setenv("WESTLAKE_HOME", str(tmp_path / "home"))
    yield
    reset_sis()


@pytest.fixture
def ps_xls_bytes() -> bytes:
    """ps.xls fixture（HTML 表格伪装、行末缺 ``</tr>``）。"""
    return (FIXTURES / "ps.xls").read_bytes()


@pytest.fixture
def ps_xls_text(ps_xls_bytes: bytes) -> str:
    return ps_xls_bytes.decode("utf-8")


@pytest.fixture
def ps_real_bytes() -> bytes:
    """真实 ps.xls 的**脱敏**副本（2026-08-30 从 SIS 导出，2026 秋学期）。

    脱敏规则：仅把任课教师姓名（中文名 + 英文拼音）替换为「教师A」..
    「教师I」占位符；课程代码 / 课程名称 / 日期 / 星期和时间 / 教室 / 状态
    均按原样保留。原件不含个人标识号。字节结构（行末缺 ``</tr>``、
    ``<br />`` 多值分隔）保持不变。教师真名/个人标识号不得出现在本文件。
    """
    return (FIXTURES / "ps_real_sanitized.xls").read_bytes()


@pytest.fixture
def ps_real_text(ps_real_bytes: bytes) -> str:
    return ps_real_bytes.decode("utf-8")


@pytest.fixture
def schedule_real_html() -> str:
    """真实课表页 fluid 网格 HTML 的**脱敏**副本（2026-09-23 登录态抓取）。

    来源：登录后 ``SSR_STUDENT_FL.SSR_COMPONENT_FL.GBL?Page=SSR_VW_CLASS_FL``
    （「View My Classes」，网格 ``WL_STDNT_ENR_VW``，10 门课 / 15 条节次）。
    脱敏规则：任课教师姓名（中文名+拼音 / 纯外文名 / 纯中文名）替换为
    「教师A」..「教师I」；学生姓名/学号替换为占位符；``ICSID``/``ptnbsid``
    会话令牌替换为 ``SANITIZED``。课程代码 / 课程名称 / 日期 / 时间 / 教室 /
    状态与 DOM 结构保持原样。教师真名/学生 PII 不得出现在本文件。
    """
    return (FIXTURES / "schedule_real_sanitized.html").read_text(encoding="utf-8")


@pytest.fixture
def ps_export_real_bytes() -> bytes:
    """与 :fixture:`schedule_real_html` 同日（2026-09-23）真实导出的
    ``ps.xls`` 脱敏副本（教师占位符映射与页面 fixture 一致）。

    用于离线锁定「页面解析 = 当场导出解析」的实测一致性。
    """
    return (FIXTURES / "ps_real_20260923_sanitized.xls").read_bytes()


@pytest.fixture
def schedule_grid_html() -> str:
    """课表页 HTML 网格 fixture。"""
    return (FIXTURES / "schedule_grid.html").read_text(encoding="utf-8")


@pytest.fixture
def grades_real_html() -> str:
    """成绩页 fluid 网格 ``WL_STU_ENRL_V2`` 的**脱敏**副本（2026-09-23 登录态抓取）。

    来源：``WL_CUSTOMIZE_MENU.WL_STU_GRADE_COM.GBL``（「My Grades」）。真实页
    38 行，此处从各学期抽取 7 行（覆盖字母等级 ``A+``/``B``/``B+``、等级制
    ``P`` 与未出分空等级）。脱敏规则：只保留网格 ``<table>`` 本身（页头问候语
    含学生姓名，已整体剔除）；``ICSID``/``ptnbsid`` 会话令牌已随页头剔除；
    课程代码 / 课程名称 / 学期 / 等级 / 学分与 DOM 结构保持原样。无个人 PII。
    """
    return (FIXTURES / "grades_grid_sanitized.html").read_text(encoding="utf-8")


@pytest.fixture
def exams_real_html() -> str:
    """考试页 fluid 网格 ``WL_EXAM_STU_VW`` 的**脱敏**副本（2026-09-23 登录态抓取）。

    来源：``WL_CUSTOMIZE_MENU.WL_EXAM_STU_COM_FL.GBL?Page=WL_EXAM_STU_FL``。
    真实页 10 门课（考试尚未排定，日期及之后各列为空），此处抽取 4 行；保留
    吸顶表头表 + 数据表两张表的真实结构（用于验证按网格 id 选表）。脱敏规则：
    只保留网格 ``<table>``（页头问候语含学生姓名，已整体剔除）；课程代码 /
    课程名称与 DOM 结构保持原样；``Date/Time/Type/Method/Venue/Seat`` 均为空
    （如实反映未排期）。无个人 PII。
    """
    return (FIXTURES / "exams_grid_sanitized.html").read_text(encoding="utf-8")


@pytest.fixture
def synth_fluid_grid_html() -> str:
    """合成 fluid 网格 fixture（非真实页面）：覆盖 ``<br />`` 多值拆分与空单元格。"""
    return (FIXTURES / "synth_fluid_grid.html").read_text(encoding="utf-8")


@pytest.fixture
def label_value_html() -> str:
    """合成 label-value fixture（非真实页面）：覆盖键值配对与空/无值标签。"""
    return (FIXTURES / "label_value_synth.html").read_text(encoding="utf-8")


@pytest.fixture
def login_page() -> str:
    """PeopleSoft 登录页（未登录时 SIS 返回的页面）。"""
    return (
        '<form id="login" name="login" method="post" action="?&cmd=login&languageCd=ENG">'
        '<input type="hidden" name="lcsrf_token" value="CSRF-1">'
        '<input type="text" id="userid" name="userid" value="">'
        '<input type="password" id="pwd" name="pwd">'
        '<input name="Submit" type="submit" value="Sign In">'
        "</form>"
    )