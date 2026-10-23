"""program 模块端到端测试：真实抓招生网 → 解析 → 数据模型。

默认被 ``-m 'not live'`` 排除（本仓库对 live 的统一约定）；
真实验证运行：``pytest src/test/program -q -m live``。

依据 2026-10-23 用户裁定，本仓库不再维护单元测试，功能验证一律走
端到端真链路；本文件即 program 功能的持久化端到端用例。
"""

from __future__ import annotations

import pytest

from westlake_survival.program import (
    CURRICULUM_SECTION_KEYS,
    EDUCATION_FEATURE_KEYS,
    MAJOR_SLUGS,
    common_courses,
    course_search,
    curriculum,
    major_plans,
    majors,
    overview,
)


@pytest.mark.live
def test_live_overview_goal_and_features() -> None:
    """培养理念页：培养目标非空，八项特色齐全且标题来自页面。"""
    data = overview()

    assert data.goal.content_text
    assert "西湖大学" in data.goal.content_text
    assert len(data.features) == len(EDUCATION_FEATURE_KEYS)
    titles = [feature.title for feature in data.features]
    assert "一人一策培养" in titles
    assert all(feature.content_text for feature in data.features)
    assert data.url.endswith("/Academics/WestlakeEducation/")


@pytest.mark.live
def test_live_curriculum_sections_and_tables() -> None:
    """课程安排页：六栏目齐全，通识两个栏目带课程简表。"""
    data = curriculum()

    keys = [section.key for section in data.sections]
    assert keys == list(CURRICULUM_SECTION_KEYS)
    by_key = {section.key: section for section in data.sections}
    # 键名与语义错位陷阱：majors 键装的是科研训练课程，title 才是官方名。
    assert by_key["majors"].title == "科研训练课程"
    assert by_key["studyAbroad"].title == "专业课程"
    assert "选定专业时间" in by_key["studyAbroad"].content_text
    for key in ("SECore", "HASSCore"):
        table = by_key[key].table
        assert table is not None
        assert table.rows
        assert all(row.items for row in table.rows)


@pytest.mark.live
def test_live_majors_eight_across_three_groups() -> None:
    """专业设置页：8 个专业分属理学/工学/医学，总览含选定时间规则。"""
    data = majors()

    assert len(data.majors) == 8
    assert {m.group for m in data.majors} == {"理学", "工学", "医学"}
    names = {m.name for m in data.majors}
    assert {"生物科学", "化学", "物理学", "数学与应用数学", "电子信息工程", "材料科学与工程", "人工智能", "临床医学"} <= names
    assert "选定专业时间" in data.summary
    assert all(m.intro_text for m in data.majors)


@pytest.mark.live
def test_live_majors_en_site() -> None:
    """英文站同构：同一组件名可解析出 8 个专业。"""
    data = majors("en")

    assert data.lang == "en"
    assert len(data.majors) == 8
    assert data.url.startswith("https://ugadmissions.westlake.edu.cn/")


@pytest.mark.live
def test_live_plan_all_eight_majors_have_credit_blocks() -> None:
    """培养方案：任一专业页含全部 8 个专业，各专业的学分块齐全。"""
    catalog = major_plans("人工智能")

    assert len(catalog.majors) == 8
    assert {m.name for m in catalog.majors} == set(MAJOR_SLUGS)
    for plan in catalog.majors:
        # 通识四个学分块每个专业都有；临床医学另有 4 个空专业课程表（官网现状）。
        assert sum(1 for req in plan.requirements if req.credits) >= 4, plan.name
        assert all(course.name for req in plan.requirements for course in req.courses), plan.name
        assert plan.intro and plan.intro[0].content_text, plan.name


@pytest.mark.live
def test_live_plan_ai_matches_published_figures() -> None:
    """人工智能专业逐项核对官网公布的学分块与专业必修课程。"""
    plan = major_plans("人工智能").find("人工智能")

    assert plan is not None
    by_title = {req.title: req for req in plan.requirements}
    assert by_title["专业必修课程"].credits == "24"
    assert by_title["专业选修课程"].credits == "18"
    assert by_title["理工基础类"].credits == "34"
    assert by_title["人文社科艺术类"].credits == "20-28"

    required = [course.name for course in by_title["专业必修课程"].courses]
    assert len(required) == 8
    assert "机器学习" in required and "深度学习" in required and "自然语言处理" in required
    nlp = next(c for c in by_title["专业必修课程"].courses if c.name == "自然语言处理")
    assert "机器学习" in nlp.prerequisite
    assert plan.course_count == 25
    assert plan.total_credits is None  # 含 20-28 区间，不硬凑合计


@pytest.mark.live
def test_live_plan_clinical_medicine_has_no_course_tables() -> None:
    """临床医学的专业课程表官网为空——如实暴露而非当成解析失败。"""
    plan = major_plans("临床医学").find("临床医学")

    assert plan is not None
    assert plan.course_count == 0
    assert plan.requirements


@pytest.mark.live
def test_live_common_courses_catalog() -> None:
    """通识课程目录：三类共 99 门，学分/学期/教师/先修齐全。"""
    catalog = common_courses()

    assert len(catalog.courses) == 99
    assert catalog.categories() == ["理工基础类", "人文社科艺术类", "基础素质类"]
    assert catalog.notices  # 人文类有标星说明

    by_title = {course.title: course for course in catalog.courses}
    algebra = by_title["代数与分析基础（上）"]
    assert algebra.credits == "7" and algebra.subject == "数学"
    tennis = by_title["网球（初级）"]
    assert tennis.credits == "1" and tennis.semester == "秋季"
    assert tennis.teachers and tennis.teachers[0].name


@pytest.mark.live
def test_live_common_courses_filters() -> None:
    """类别片段与关键词过滤都在本地生效。"""
    pe = common_courses(category="素质")
    assert len(pe.courses) == 24
    assert all(course.category == "基础素质类" for course in pe.courses)

    writing = common_courses(keyword="写作")
    assert writing.courses
    assert all("写作" in (course.title + course.subject + course.description_text) for course in writing.courses)


@pytest.mark.live
def test_live_course_search_across_sources() -> None:
    """跨源搜索：同一门课在通识与各专业培养方案里的归属与学分差异。"""
    hits = course_search("机器学习")

    sources = {hit.source for hit in hits}
    assert "人工智能·专业必修课程" in sources
    assert "电子信息工程·专业必修课程" in sources
    ai_hit = next(hit for hit in hits if hit.source == "人工智能·专业必修课程")
    assert ai_hit.credits == "4"
    math_hit = next(hit for hit in hits if hit.source == "数学与应用数学·专业选修课程")
    assert math_hit.credits == "3"

    # 只在通识里有的课，--no-plans 口径也应有命中
    only_common = course_search("写作与沟通", include_major_plans=False)
    assert any(hit.source.startswith("通识·") for hit in only_common)
