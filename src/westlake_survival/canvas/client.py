"""Canvas REST API 客户端。

Canvas (Instructure) 自带标准 REST API，认证方式是 Bearer Token：

    GET https://canvas.westlake.edu.cn/api/v1/courses
    Authorization: Bearer <token>

学生可以在 Canvas 网页「账户 → 设置 → 新建访问令牌」自助生成 token
（是否开放由管理员控制）。本模块不引入 sso 依赖，纯 token 认证。

Token 解析顺序（`:class:`CanvasClient` 构造时确定）：

1. 显式传入的 ``token`` 参数；
2. 环境变量 ``WESTLAKE_CANVAS_TOKEN``；
3. 文件 ``~/.westlake_survival/canvas_token.txt`` 的首行（``strip`` 后）；
4. 都没有 → :class:`westlake_survival.exceptions.AuthError`。

所有异常都是 :mod:`westlake_survival.exceptions` 中的类型，调用方只需
捕获 ``WestlakeError``。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

import requests

from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.canvas.models import (
    CHINA_TZ,
    QUIZ_SUBMISSION_TYPE,
    Announcement,
    Assignment,
    Course,
    ExamEvent,
    File,
    QuizItem,
    User,
)
from westlake_survival.exceptions import AuthError, NotFound, ParseError, WestlakeError

#: Canvas API 根地址；测试可用 ``WESTLAKE_CANVAS_BASE`` 环境变量覆盖。
CANVAS_BASE = "https://canvas.westlake.edu.cn/api/v1"

#: 承载 API token 的环境变量名。
TOKEN_ENV_VAR = "WESTLAKE_CANVAS_TOKEN"

#: 默认 token 文件名（位于配置根目录，通常 ``~/.westlake_survival``）。
TOKEN_FILENAME = "canvas_token.txt"

#: 分页时每页条数（Canvas 上限为 100，这里取保守的 50）。
PER_PAGE = 50

#: 下载文件时的分块大小（字节）。
DOWNLOAD_CHUNK_SIZE = 8192

#: 分页翻页的页数上限；防止服务端 ``rel=next`` 成环导致无限请求。
MAX_PAGES = 200

#: 非 2xx 错误消息里附带的响应体长度上限。
_ERROR_BODY_LIMIT = 200

_TOKEN_HELP = (
    "未找到 Canvas API token。请在 Canvas 网页「账户 → 设置 → 新建访问令牌」"
    f"生成令牌，然后设置环境变量 {TOKEN_ENV_VAR}，或写入 "
    f"~/.westlake_survival/{TOKEN_FILENAME}（首行）。"
)


def resolve_base_url() -> str:
    """返回 API 根地址，优先取环境变量 ``WESTLAKE_CANVAS_BASE``。"""
    return os.environ.get("WESTLAKE_CANVAS_BASE") or CANVAS_BASE


def token_file_path() -> Path:
    """返回 token 文件路径，遵循 ``WESTLAKE_HOME`` 重定位约定。"""
    override = os.environ.get("WESTLAKE_HOME")
    root = Path(override).expanduser() if override else Path.home() / ".westlake_survival"
    return root / TOKEN_FILENAME


def resolve_token(token: str | None = None) -> str | None:
    """按「参数 > 环境变量 > 文件首行」顺序解析 token，找不到返回 ``None``。"""
    if token:
        return token.strip()
    env_token = os.environ.get(TOKEN_ENV_VAR)
    if env_token and env_token.strip():
        return env_token.strip()
    path = token_file_path()
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return first_line or None


class CanvasClient:
    """Canvas REST API 客户端。

    Args:
        token: API token；``None`` 时按上述三级顺序解析。
        session: 可注入的 :class:`requests.Session`（测试用）。
        base_url: 覆盖 API 根地址（测试用）。
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        session: requests.Session | None = None,
        base_url: str | None = None,
    ) -> None:
        resolved = resolve_token(token)
        if not resolved:
            raise AuthError(_TOKEN_HELP)
        self._token = resolved
        self._session = session if session is not None else http_session()
        self.base_url = (base_url or resolve_base_url()).rstrip("/")

    # ------------------------------------------------------------------
    # 内部：请求、错误映射、分页
    # ------------------------------------------------------------------
    @property
    def token(self) -> str:
        """当前使用的 token（只读）。"""
        return self._token

    def _require_token(self) -> None:
        """公开方法统一入口守卫：token 缺失即抛 ``AuthError``。"""
        if not self._token:
            raise AuthError(_TOKEN_HELP)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def _raise_for_status(self, response: requests.Response) -> None:
        """把非 2xx 响应映射为本库异常。"""
        status = response.status_code
        if 200 <= status < 300:
            return
        body = self._response_text(response)[:_ERROR_BODY_LIMIT]
        if status == 401:
            raise AuthError(f"Canvas 认证失败（HTTP 401）：token 无效或已过期。{body}")
        if status == 404:
            raise NotFound(f"Canvas 资源不存在（HTTP 404）：{body}")
        raise WestlakeError(f"Canvas 请求失败（HTTP {status}）：{body}")

    @staticmethod
    def _response_text(response: requests.Response) -> str:
        try:
            text = response.text
        except Exception:  # pragma: no cover - 防御性
            return ""
        return text or ""

    def _json(self, response: requests.Response) -> Any:
        """解析 JSON；失败抛 ``ParseError``。"""
        try:
            return response.json()
        except ValueError as exc:
            snippet = self._response_text(response)[:_ERROR_BODY_LIMIT]
            raise ParseError(f"Canvas 返回内容不是合法 JSON：{snippet}") from exc

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> requests.Response:
        self._require_token()
        response = self._session.get(
            self._url(path),
            params=dict(params) if params else None,
            headers=self._auth_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise_for_status(response)
        return response

    def _get_url(self, url: str, params: Mapping[str, Any] | None = None) -> requests.Response:
        """按完整 URL 请求（分页翻页用）；错误映射同 :meth:`_get`。"""
        response = self._session.get(
            url,
            params=dict(params) if params else None,
            headers=self._auth_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise_for_status(response)
        return response

    def _paginate(self, path: str, params: Mapping[str, Any] | None = None) -> Iterator[dict]:
        """按 Link 响应头 ``rel=next`` 翻页，逐条 yield 字典。

        Canvas 的分页链接是一个完整 URL（自带查询串），翻到没有 ``next``
        为止；首页默认带 ``per_page``。为防御服务端把 ``next`` 指回已访问
        URL（或成环）导致的无限请求，维护已访问集合并以 ``MAX_PAGES`` 兜底。
        """
        self._require_token()
        current_url: str | None = self._url(path)
        current_params: Mapping[str, Any] | None = dict(params or {})
        if current_params is not None:
            current_params.setdefault("per_page", PER_PAGE)
        visited_urls: set[str] = set()
        pages = 0
        while current_url:
            if current_url in visited_urls:
                break
            visited_urls.add(current_url)
            pages += 1
            if pages > MAX_PAGES:
                break
            response = self._get_url(current_url, current_params)
            data = self._json(response)
            if isinstance(data, Mapping):
                items: list[Any] = [data]
            elif isinstance(data, list):
                items = data
            else:
                raise ParseError(f"Canvas 分页接口返回了非列表内容：{type(data).__name__}")
            for item in items:
                if isinstance(item, Mapping):
                    yield dict(item)
            links = getattr(response, "links", None) or {}
            nxt = links.get("next") if isinstance(links, Mapping) else None
            if nxt and nxt.get("url"):
                current_url = nxt["url"]
                current_params = None  # next URL 已含完整查询串
            else:
                current_url = None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def me(self) -> User:
        """当前令牌对应的用户（``GET /users/self``）。"""
        return User.from_json(self._json(self._get("/users/self")))

    def list_courses(self, enrollment_state: str = "active") -> list[Course]:
        """列出当前用户的课程（``GET /courses``）。"""
        params = {"enrollment_state": enrollment_state} if enrollment_state else None
        return [Course.from_json(item) for item in self._paginate("/courses", params)]

    def get_course(self, course_id: int | str) -> Course:
        """取单个课程详情（``GET /courses/:id``）。"""
        return Course.from_json(self._json(self._get(f"/courses/{course_id}")))

    def list_assignments(
        self,
        course_id: int | str,
        *,
        bucket: str | None = None,
        include_future: bool = False,
    ) -> list[Assignment]:
        """列出课程的作业（``GET /courses/:id/assignments``）。

        Args:
            course_id: 课程 id。
            bucket: Canvas 的 ``bucket`` 过滤（``upcoming`` / ``past`` /
                ``future`` / ``undated`` 等）。
            include_future: 为 ``True`` 时附带 ``include_future=true`` 查询参数。
        """
        params: dict[str, Any] = {}
        if bucket:
            params["bucket"] = bucket
        if include_future:
            params["include_future"] = "true"
        rows = self._paginate(f"/courses/{course_id}/assignments", params)
        return [Assignment.from_json(item) for item in rows]

    def upcoming_deadlines(self, limit: int = 10) -> list[Assignment]:
        """汇总所有 active 课程中即将到期的作业，按截止时间升序。

        遍历 active 课程的 ``bucket=upcoming`` 作业，跳过 ``due_at`` 为
        ``None`` 的条目，合并后按 ``due_at`` 升序取前 *limit* 条。
        """
        collected: list[Assignment] = []
        for course in self.list_courses(enrollment_state="active"):
            if course.id is None:
                continue
            for assignment in self.list_assignments(course.id, bucket="upcoming"):
                if assignment.due_at is None:
                    continue
                if assignment.course_id is None:
                    assignment.course_id = course.id
                collected.append(assignment)
        collected.sort(key=lambda item: item.due_at)
        return collected[:limit]

    def quizzes(self, course_id: int | str | None = None) -> list[QuizItem]:
        """列出测验型作业（``submission_types`` 含 ``online_quiz``）。

        Canvas 没有独立的考试对象，期末考试通常是一个 ``online_quiz`` 型
        作业，故以此近似考试安排。实现基于 ``GET /courses/:id/assignments``
        拉全量后按 ``submission_types`` 过滤（Canvas 该端点无服务端过滤参数）。

        Args:
            course_id: 课程 id；``None`` 时遍历全部 active 课程。
        """
        if course_id is None:
            collected: list[QuizItem] = []
            for course in self.list_courses(enrollment_state="active"):
                if course.id is None:
                    continue
                collected.extend(self.quizzes(course.id))
            return collected
        quizzes: list[QuizItem] = []
        for row in self._paginate(f"/courses/{course_id}/assignments"):
            assignment = Assignment.from_json(row)
            if QUIZ_SUBMISSION_TYPE not in assignment.submission_types:
                continue
            quiz = QuizItem.from_json(row)
            if quiz.course_id is None:
                quiz.course_id = self._coerce_int(course_id)
            quizzes.append(quiz)
        return quizzes

    def exam_events(self, course_id: int | str | None = None) -> list[ExamEvent]:
        """列出课程日历事件（``GET /calendar_events``）作为考试信号。

        Canvas 的 ``calendar_events`` 只认 ``type=event`` / ``type=assignment``
        （没有 ``type=exam``），事件本身也不带「是否考试」标记，因此这里取
        ``type=event`` 的事件（排除 ``type=assignment``，避免与 :meth:`quizzes`
        重复），**不做关键词过滤**——课程日历里的自建事件通常就是考试安排。

        Args:
            course_id: 课程 id；给出时附带 ``context_codes[]=course_<id>``，
                否则拉取全部 context 的事件。
        """
        params: dict[str, Any] = {"type": "event"}
        if course_id is not None:
            params["context_codes[]"] = f"course_{course_id}"
        events: list[ExamEvent] = []
        for row in self._paginate("/calendar_events", params):
            event = ExamEvent.from_json(row)
            if course_id is not None and event.course_id is None:
                event.course_id = self._coerce_int(course_id)
            events.append(event)
        return events

    @staticmethod
    def _exam_sort_time(item: QuizItem | ExamEvent) -> datetime | None:
        """取条目用于排序/过滤的时间（quiz 用 ``due_at``，事件用 ``start_at``）。"""
        if isinstance(item, QuizItem):
            return item.due_at
        return item.start_at

    def exams(self, days: int | None = None) -> list[QuizItem | ExamEvent]:
        """考试安排汇总：测验型作业 ∪ 课程日历事件，按时间升序。

        Args:
            days: 只保留从当前时刻起未来 ``days`` 天内（含今天）且时间不早于
                当前时刻的条目；``None`` 表示不过滤。无时间的条目恒被排除。
        """
        items: list[QuizItem | ExamEvent] = [*self.quizzes(), *self.exam_events()]
        far_future = datetime.max.replace(tzinfo=CHINA_TZ)
        if days is not None:
            now = datetime.now(CHINA_TZ)
            horizon = now + timedelta(days=days)
            items = [
                item
                for item in items
                if (when := self._exam_sort_time(item)) is not None
                and now <= when <= horizon
            ]
        items.sort(key=lambda item: self._exam_sort_time(item) or far_future)
        return items

    def list_files(self, course_id: int | str) -> list[File]:
        """列出课程文件（``GET /courses/:id/files``）。"""
        rows = self._paginate(f"/courses/{course_id}/files")
        return [File.from_json(item) for item in rows]

    def download_file(self, file_id: int | str, dest: Path | str) -> Path:
        """下载文件到 *dest*（流式写入），返回 *dest*。

        先 ``GET /files/:id`` 拿到带 ``verifier`` 的下载地址，再流式拉取
        内容。下载地址自带签名，因此内容请求不附加 ``Authorization``
        （避免把 token 泄漏给文件 CDN）。
        """
        self._require_token()
        meta = self._json(self._get(f"/files/{file_id}"))
        url = meta.get("url") if isinstance(meta, Mapping) else None
        if not url:
            raise ParseError(f"文件 {file_id} 的元数据中没有下载地址 url")
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        response = self._session.get(url, timeout=DEFAULT_TIMEOUT, stream=True)
        try:
            self._raise_for_status(response)
            with open(destination, "wb") as handle:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return destination

    def list_announcements(self, course_id: int | str) -> list[Announcement]:
        """列出课程公告（``GET /courses/:id/discussion_topics``）。"""
        params = {"only_announcements": "true"}
        rows = self._paginate(f"/courses/{course_id}/discussion_topics", params)
        announcements: list[Announcement] = []
        for item in rows:
            announcement = Announcement.from_json(item)
            if announcement.course_id is None:
                announcement.course_id = self._coerce_int(course_id)
            announcements.append(announcement)
        return announcements

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


__all__ = [
    "CANVAS_BASE",
    "PER_PAGE",
    "TOKEN_ENV_VAR",
    "TOKEN_FILENAME",
    "CanvasClient",
    "resolve_base_url",
    "resolve_token",
    "token_file_path",
]
