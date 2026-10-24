"""双语源（lang 参数）端到端测试：离线查字典结构 + live 真抓英文主站。

离线用例（默认随 ``-m 'not live'`` 跑）：8 个内容模块（含已完成的 news）都有
``*_URLS`` 与 ``CACHE_BY_LANG`` 字典，en 键指向英文主站 en.westlake.edu.cn
（news 的英文路径为 ``all_news/``，与其余模块的同路径不同名），且 zh 的 URL /
缓存名与历史值**逐字一致**（防止中文 ETag 缓存失效）。

live 用例（``-m live`` 才跑）：每个模块用 ``lang="en"`` 真实取数，断言条目
非空且内容以 ASCII 为主（英文站特征；英文标题里偶有 U+2019 等排版字符，
阈值取 0.8）。

运行：``pytest src/test/bilingual -q``（离线）／
``pytest src/test/bilingual -q -m live``（真联网）。
"""

from __future__ import annotations

import pytest

from westlake_survival import calendar, campus, careers, contact, events, faculty, news, research

#: 英文主站根。
_EN_HOST = "https://en.westlake.edu.cn/"

#: ASCII 占比阈值（英文内容里偶见 ’ – 等非 ASCII 排版字符）。
_ASCII_RATIO = 0.8

#: (模块, URLS 常量名, 原 URL 常量名, 历史 zh 缓存名, 期望 en 缓存名)。
_CASES = [
    (news, "NEWS_URLS", "NEWS_URL", "news/allnews.html", "news/allnews_en.html"),
    (
        events,
        "EVENTS_URLS",
        "EVENTS_URL",
        "events/event_calendars.html",
        "events/event_calendars_en.html",
    ),
    (
        careers,
        "POSITIONS_URLS",
        "POSITIONS_URL",
        "careers/positions.html",
        "careers/positions_en.html",
    ),
    (
        research,
        "RESEARCH_URLS",
        "RESEARCH_URL",
        "research/research_at_westlake.html",
        "research/research_at_westlake_en.html",
    ),
    (
        campus,
        "HOUSING_DINING_URLS",
        "HOUSING_DINING_URL",
        "campus/housing_dining.html",
        "campus/housing_dining_en.html",
    ),
    (
        contact,
        "CONTACT_URLS",
        "CONTACT_URL",
        "contact/contact_us.html",
        "contact/contact_us_en.html",
    ),
    (
        calendar,
        "CALENDAR_URLS",
        "CALENDAR_URL",
        "calendar/academic_calendar.html",
        "calendar/academic_calendar_en.html",
    ),
    (
        faculty,
        "LIST_URLS",
        "LIST_URL",
        "faculty/faculty_list.html",
        "faculty/faculty_list_en.html",
    ),
]


def _ascii_ratio(text: str) -> float:
    """文本中 ASCII 字符占比；空串为 0。"""
    if not text:
        return 0.0
    return sum(1 for ch in text if ord(ch) < 128) / len(text)


# --------------------------------------------------------------------------- #
# 离线：字典结构与 zh 缓存兼容性
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "module, urls_name, url_name, zh_cache, en_cache",
    _CASES,
    ids=[module.__name__.rsplit(".", 1)[-1] for module, *_ in _CASES],
)
def test_bilingual_dicts_offline(
    module, urls_name: str, url_name: str, zh_cache: str, en_cache: str
) -> None:
    """8 个模块都有 URLS / CACHE_BY_LANG 字典，zh 值与历史逐字一致。"""
    urls = getattr(module, urls_name)
    cache = module.CACHE_BY_LANG
    zh_url = getattr(module, url_name)

    assert urls["zh"] == zh_url, "zh 源 URL 必须逐字保留"
    assert cache["zh"] == zh_cache, "zh 缓存名必须与历史值逐字一致（防中文缓存失效）"
    assert urls["en"].startswith(_EN_HOST), "en 键必须指向英文主站 en.westlake.edu.cn"
    assert urls["en"] != urls["zh"]
    assert cache["en"] == en_cache, "en 缓存须为「原名去扩展名_en.扩展名」且另存一份"
    assert cache["en"] != cache["zh"]
    if module is news:
        # 英文全量列表路径与中文不同名：allnews/ → all_news/
        assert urls["en"].endswith("/news_events/westlakenews/all_news/")
    else:
        # 英文主站与中文站同路径（同组件名）
        assert urls["en"] == _EN_HOST + zh_url.removeprefix("https://www.westlake.edu.cn/")


# --------------------------------------------------------------------------- #
# live：lang="en" 真实取数（各模块一例）
# --------------------------------------------------------------------------- #
@pytest.mark.live
def test_live_events_en() -> None:
    items = events.load_events(limit=5, lang="en", refresh=True)

    assert items
    assert _ascii_ratio(items[0].title) >= _ASCII_RATIO
    assert items[0].url.startswith(_EN_HOST)


@pytest.mark.live
def test_live_careers_en() -> None:
    people = careers.positions(limit=5, lang="en", refresh=True)

    assert people
    assert _ascii_ratio(people[0].title) >= _ASCII_RATIO
    assert people[0].url.startswith(_EN_HOST)


@pytest.mark.live
def test_live_research_en() -> None:
    items = research.latest(limit=5, lang="en", refresh=True)

    assert items
    assert _ascii_ratio(items[0].title) >= _ASCII_RATIO
    assert items[0].url.startswith(_EN_HOST)


@pytest.mark.live
def test_live_campus_en() -> None:
    data = campus.load(refresh=True, lang="en")

    spots = [spot for group in data.dining.values() for spot in group]
    assert spots, "英文页应有 Dining Halls / Bakeries 餐饮块"
    assert set(data.dining) <= set(campus.DINING_KINDS_EN)
    assert _ascii_ratio(spots[0].name) >= _ASCII_RATIO
    assert data.services, "英文页超市/银行/邮局等块应透传为 services"
    assert _ascii_ratio(data.services[0].campus) >= _ASCII_RATIO


@pytest.mark.live
def test_live_contact_en() -> None:
    infos = contact.campuses(refresh=True, lang="en")

    assert infos
    assert _ascii_ratio(infos[0].name) >= _ASCII_RATIO
    assert _ascii_ratio(infos[0].address) >= _ASCII_RATIO

    entries = contact.contacts(lang="en")
    assert entries
    assert _ascii_ratio(entries[0].label) >= _ASCII_RATIO


@pytest.mark.live
def test_live_calendar_en() -> None:
    cal = calendar.AcademicCalendar.load(refresh=True, lang="en")

    assert cal.semesters
    semester = cal.semesters[0]
    assert _ascii_ratio(semester.name) >= _ASCII_RATIO
    assert semester.events
    assert _ascii_ratio(semester.events[0].title) >= _ASCII_RATIO


@pytest.mark.live
def test_live_faculty_en() -> None:
    people = faculty.members(lang="en", limit=5)

    assert people
    assert _ascii_ratio(people[0].name) >= _ASCII_RATIO
    assert all(person.url.startswith(_EN_HOST) for person in people)


@pytest.mark.live
def test_live_news_en() -> None:
    items = news.latest(limit=5, lang="en", refresh=True)

    assert items
    assert _ascii_ratio(items[0].title) >= _ASCII_RATIO
