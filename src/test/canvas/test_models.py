"""Canvas 模型解析测试（全部离线）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from westlake_survival.canvas.models import (
    CHINA_TZ,
    Announcement,
    Assignment,
    Course,
    File,
    User,
    parse_datetime,
)


def test_parse_datetime_z_suffix_converted_to_china_tz():
    parsed = parse_datetime("2026-09-22T10:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 8 * 3600
    assert parsed.hour == 18  # 10:00 UTC -> 18:00 +08:00
    assert parsed.tzinfo == CHINA_TZ
    assert isinstance(parsed, datetime)


def test_parse_datetime_offset_string_kept_aware():
    parsed = parse_datetime("2026-09-22T10:00:00+00:00")
    assert parsed is not None
    assert parsed.hour == 18


def test_parse_datetime_none_and_garbage():
    assert parse_datetime(None) is None
    assert parse_datetime("") is None
    assert parse_datetime("   ") is None
    assert parse_datetime("not-a-date") is None
    assert parse_datetime(12345) is None


def test_parse_datetime_naive_treated_as_utc():
    parsed = parse_datetime("2026-09-22T00:00:00")
    assert parsed is not None
    assert parsed.tzinfo == CHINA_TZ
    assert parsed.hour == 8
    # 中国无夏令时：全年固定 +08:00
    winter = parse_datetime("2026-01-15T00:00:00Z")
    assert winter is not None
    assert winter.utcoffset() == timedelta(hours=8)
    assert winter.hour == 8


def test_user_from_json_and_missing_fields():
    user = User.from_json({"id": 7, "name": "张三", "login_id": "zs", "primary_email": "z@w.edu"})
    assert (user.id, user.name, user.login_id, user.primary_email) == (7, "张三", "zs", "z@w.edu")
    empty = User.from_json({})
    assert empty.id is None and empty.name is None
    assert User.from_json(None).id is None


def test_course_term_nested_and_top_level():
    nested = Course.from_json({"id": 1, "name": "ML", "term": {"name": "2026 Fall"}})
    assert nested.term_name == "2026 Fall"
    flat = Course.from_json({"id": 2, "term_name": "2026 Spring"})
    assert flat.term_name == "2026 Spring"
    # 顶层优先于嵌套
    both = Course.from_json({"term_name": "Top", "term": {"name": "Nested"}})
    assert both.term_name == "Top"


def test_course_time_fields_parsed():
    course = Course.from_json(
        {"id": 1, "start_at": "2026-09-01T00:00:00Z", "end_at": None, "is_public": False}
    )
    assert course.start_at is not None and course.start_at.hour == 8
    assert course.end_at is None
    assert course.is_public is False


def test_assignment_from_json_and_tolerances():
    item = Assignment.from_json(
        {
            "id": 10,
            "course_id": 1,
            "name": "HW1",
            "description": "<p>x</p>",
            "due_at": "2026-10-01T15:59:59Z",
            "points_possible": 100.0,
            "submission_types": ["online_upload", "online_text_entry"],
            "html_url": "https://canvas.westlake.edu.cn/courses/1/assignments/10",
            "locked_for_user": True,
        }
    )
    assert item.id == 10 and item.course_id == 1
    assert item.points_possible == 100.0
    assert item.submission_types == ["online_upload", "online_text_entry"]
    assert item.due_at is not None and item.due_at.hour == 23  # 15:59 UTC -> 23:59
    # 缺字段 / submission_types 非列表
    empty = Assignment.from_json({})
    assert empty.submission_types == [] and empty.due_at is None
    weird = Assignment.from_json({"submission_types": "none"})
    assert weird.submission_types == []


def test_file_from_json_filename_fallback():
    item = File.from_json(
        {"id": 3, "filename": "a.pdf", "size": 10, "url": "https://x/y", "created_at": "2026-01-01T00:00:00Z"}
    )
    assert item.display_name == "a.pdf"
    assert item.size == 10
    assert item.url == "https://x/y"
    assert item.created_at is not None
    assert File.from_json({}).display_name is None


def test_announcement_from_json():
    item = Announcement.from_json(
        {
            "id": 5,
            "course_id": 2,
            "title": "欢迎",
            "message": "<p>hi</p>",
            "posted_at": "2026-09-10T02:30:00Z",
            "html_url": "https://canvas.westlake.edu.cn/courses/2/discussion_topics/5",
        }
    )
    assert item.course_id == 2 and item.title == "欢迎"
    assert item.posted_at is not None and item.posted_at.hour == 10
    empty = Announcement.from_json(None)
    assert empty.id is None and empty.posted_at is None
