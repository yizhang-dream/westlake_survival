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

import mimetypes
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import requests

from westlake_survival._net import DEFAULT_TIMEOUT, http_session
from westlake_survival.canvas.models import (
    CHINA_TZ,
    QUIZ_SUBMISSION_TYPE,
    SUBMISSION_TYPE_TEXT,
    SUBMISSION_TYPE_UPLOAD,
    SUBMISSION_TYPE_URL,
    Announcement,
    Assignment,
    Course,
    ExamEvent,
    File,
    QuizItem,
    Submission,
    User,
)
from westlake_survival.exceptions import (
    ActionError,
    AuthError,
    NotFound,
    ParseError,
    WestlakeError,
)

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

#: 文件上传（传输文件本体）的超时秒数；大文件走 VPN 时 15s 不够用。
UPLOAD_TIMEOUT = 120.0

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
        self._session = session if session is not None else http_session()
        if resolved:
            self._token = resolved
        else:
            # 统一认证回退：无 token 时用统一密码登 Canvas（IAM CAS，实测
            # 会话 Cookie 可直接调 REST API，2026-10-24）。凭据沿用教务的
            # 四级来源；一次失败按「无凭据」报错，不猜口令。
            self._token = None
            self._session = self._iam_canvas_session()
            self._iam_session = True
        self.base_url = (base_url or resolve_base_url()).rstrip("/")

    # ------------------------------------------------------------------
    # 内部：请求、错误映射、分页
    # ------------------------------------------------------------------
    @property
    def token(self) -> str:
        """当前使用的 token（只读）。"""
        return self._token

    def _require_token(self) -> None:
        """公开方法统一入口守卫：token 与统一会话都没有时才抛 ``AuthError``。"""
        if not self._token and not getattr(self, "_iam_session", False):
            raise AuthError(_TOKEN_HELP)

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            # 统一认证会话模式：认证靠 Cookie，不带 Authorization 头。
            return {"Accept": "application/json"}
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    @staticmethod
    def _iam_canvas_session() -> "requests.Session":
        """用已存统一凭据登 Canvas（IAM CAS）；失败抛 ``AuthError``。"""
        try:
            from westlake_survival.iam import canvas_login
            from westlake_survival.sso import read_credentials

            user, password = read_credentials()
        except Exception as exc:
            raise AuthError(
                "未找到 Canvas token，也没有可用统一凭据。"
                "可设 WESTLAKE_CANVAS_TOKEN，或先用 westlake setup 配置统一密码。"
            ) from exc
        try:
            return canvas_login(user, password)
        except Exception as exc:
            raise AuthError(f"统一认证登 Canvas 失败：{exc}") from exc


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

    def _post(
        self,
        path: str,
        *,
        data: Any = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> requests.Response:
        """带认证的 POST；错误映射同 :meth:`_get`。"""
        self._require_token()
        response = self._session.post(
            self._url(path),
            data=data,
            headers=self._auth_headers(),
            timeout=timeout,
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

    def course_grades(self, enrollment_state: str = "active") -> list[dict]:
        """列出课程的当前/最终成绩（``include[]=total_scores``）。

        ``GET /courses?include[]=total_scores&enrollment_state=active`` 会在每门课的
        ``enrollments[]`` 里附带 ``grades``（``current_score`` / ``current_grade`` /
        ``final_score`` / ``final_grade``）。老师未发布成绩时对应字段为 ``None``。

        Returns:
            ``[{name, course_code, term_name, current_score, current_grade,
            final_score, final_grade}]``，按课程名排序。
        """
        params = {
            "enrollment_state": enrollment_state,
            "include[]": "total_scores",
        }
        rows: list[dict] = []
        for item in self._paginate("/courses", params):
            if not isinstance(item, dict):
                continue
            grades: dict = {}
            for enrollment in item.get("enrollments") or []:
                if isinstance(enrollment, Mapping) and enrollment.get("grades"):
                    grades = dict(enrollment["grades"])
                    break
            course = Course.from_json(item)
            rows.append(
                {
                    "name": course.name or "",
                    "course_code": course.course_code or "",
                    "term_name": course.term_name or "",
                    "current_score": grades.get("current_score"),
                    "current_grade": grades.get("current_grade"),
                    "final_score": grades.get("final_score"),
                    "final_grade": grades.get("final_grade"),
                }
            )
        return sorted(rows, key=lambda r: r["name"])

    def todo(self, limit: int = 20) -> list[dict]:
        """Canvas 待办（``GET /users/self/todo``）。

        每条待办带 ``context_name``（课程名）与内嵌 ``assignment``；按截止
        时间升序、无截止时间的排最后。

        Returns:
            ``[{type, course, title, due_at, url}]``。
        """
        rows: list[dict] = []
        for item in self._paginate("/users/self/todo"):
            if not isinstance(item, dict):
                continue
            assignment = item.get("assignment") or {}
            rows.append(
                {
                    "type": item.get("type") or "",
                    "course": item.get("context_name") or "",
                    "title": assignment.get("name") or item.get("title") or "",
                    "due_at": assignment.get("due_at") or item.get("due_at") or "",
                    "url": item.get("html_url") or assignment.get("html_url") or "",
                }
            )
        rows.sort(key=lambda row: row["due_at"] or "9999")
        return rows[:limit]

    def modules(self, course_id: int | str) -> list[dict]:
        """课程模块与条目（``GET /courses/:id/modules?include[]=items``）。

        Returns:
            ``[{name, count, items: [{title, type, url}]}]``，按模块顺序。
        """
        params = {"include[]": "items", "per_page": 100}
        result: list[dict] = []
        for module in self._paginate(f"/courses/{course_id}/modules", params):
            if not isinstance(module, dict):
                continue
            items = [
                {
                    "title": item.get("title") or "",
                    "type": item.get("type") or "",
                    "url": item.get("html_url") or item.get("external_url") or "",
                }
                for item in (module.get("items") or [])
                if isinstance(item, dict)
            ]
            result.append(
                {"name": module.get("name") or "", "count": len(items), "items": items}
            )
        return result

    def discussions(self, course_id: int | str) -> list[dict]:
        """课程讨论（``GET /courses/:id/discussion_topics``）。

        Returns:
            ``[{title, unread, replies, posted, url}]``。
        """
        rows: list[dict] = []
        for item in self._paginate(
            f"/courses/{course_id}/discussion_topics", {"per_page": 20}
        ):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "title": item.get("title") or "",
                    "unread": item.get("unread_count") or 0,
                    "replies": item.get("discussion_subentry_count") or 0,
                    "posted": item.get("posted_at") or "",
                    "url": item.get("html_url") or "",
                }
            )
        return rows

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

    # ------------------------------------------------------------------
    # 作业提交（写操作）：定位作业 → 上传文件 → POST submission → 回读
    # ------------------------------------------------------------------
    def get_assignment(self, course_id: int | str, assignment_id: int | str) -> Assignment:
        """取单个作业详情（``GET /courses/:cid/assignments/:aid``）。"""
        return Assignment.from_json(
            self._json(self._get(f"/courses/{course_id}/assignments/{assignment_id}"))
        )

    def find_course(self, keyword: str) -> Course:
        """按课程 id 或名称关键词定位唯一课程。

        *keyword* 为纯数字时按课程 id 精确取；否则在 active 课程的
        ``name`` / ``course_code`` 上做大小写不敏感的子串匹配。零命中抛
        :class:`NotFound`，多个命中抛 :class:`ActionError`（附候选清单）。
        """
        course_id = self._coerce_int(str(keyword).strip())
        if course_id is not None:
            return self.get_course(course_id)
        text = str(keyword).strip().lower()
        if not text:
            raise ActionError("课程关键词为空：请给课程 id 或名称关键词。")
        matches = [
            course
            for course in self.list_courses()
            if text in (course.name or "").lower() or text in (course.course_code or "").lower()
        ]
        if not matches:
            raise NotFound(
                f"没有匹配「{keyword}」的 active 课程；"
                "请用 `westlake canvas courses` 查看课程名，或直接用课程 id。"
            )
        if len(matches) > 1:
            listed = "；".join(
                f"{c.course_code or ''} {c.name}（id={c.id}）" for c in matches[:8]
            )
            raise ActionError(f"「{keyword}」匹配到多门课程：{listed}。请换更精确的关键词或用 id。")
        return matches[0]

    def find_assignment(self, course_id: int | str, keyword: str) -> Assignment:
        """按作业 id 或名称关键词定位课程内唯一作业（规则同 :meth:`find_course`）。"""
        assignment_id = self._coerce_int(str(keyword).strip())
        if assignment_id is not None:
            return self.get_assignment(course_id, assignment_id)
        text = str(keyword).strip().lower()
        if not text:
            raise ActionError("作业关键词为空：请给作业 id 或名称关键词。")
        matches = [
            assignment
            for assignment in self.list_assignments(course_id)
            if text in (assignment.name or "").lower()
        ]
        if not matches:
            raise NotFound(
                f"课程 {course_id} 下没有匹配「{keyword}」的作业；"
                "请用 `westlake canvas assignments --course …` 查看作业名或 id。"
            )
        if len(matches) > 1:
            listed = "；".join(f"{a.name}（id={a.id}）" for a in matches[:8])
            raise ActionError(f"「{keyword}」匹配到多个作业：{listed}。请换更精确的关键词或用 id。")
        return matches[0]

    def upload_course_file(self, course_id: int | str, file_path: Path | str) -> File:
        """把本地文件上传到课程文件区，返回 :class:`File`（含 ``id``）。

        供 :meth:`submit_assignment` 内部使用；独立调用产生的文件会留在
        课程文件区，不会自动附着到任何作业。注意：部分 Canvas 实例
        （如西湖）禁止学生向课程文件区上传，此时会抛 :class:`AuthError`，
        提交流程内部会自动退回本人文件区（见 :meth:`_upload_for_submission`）。
        """
        return self._upload_file(f"/courses/{course_id}/files", Path(file_path))

    def _upload_for_submission(self, course_id: int | str, file_path: Path) -> File:
        """为提交作业上传文件：先课程文件区，被拒（401）时退回本人文件区。

        Canvas 官方流程把提交文件传到课程文件区，但西湖实例对学生关闭了
        该入口（HTTP 401 unauthorized）；本人文件区上传可用，且
        ``POST submissions`` 引用本人文件 id 同样生效（提交时服务端会克隆
        文件到提交记录），两条路最终效果一致。
        """
        try:
            return self.upload_course_file(course_id, file_path)
        except AuthError:
            return self._upload_file("/users/self/files", file_path)

    def _upload_file(self, context_path: str, file_path: Path) -> File:
        """Canvas 三步文件上传：预检（notify）→ 上传本体 → 服务端落位。

        预检响应给出一次性的 ``upload_url`` + ``upload_params``；上传本体
        时**不能再带 Authorization 头**（``upload_url`` 可能是 S3 等外站
        预签名地址），认证信息已在预检阶段绑定。requests 会自动跟随上传
        后的 303 重定向，最终响应体即文件 JSON。
        """
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            raise ActionError(f"无法读取文件 {file_path}：{exc}") from exc
        name = file_path.name
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        notify = self._post(
            f"{context_path}",
            data={"name": name, "size": str(size), "content_type": content_type},
        )
        info = self._json(notify)
        upload_url = info.get("upload_url") if isinstance(info, Mapping) else None
        upload_params = info.get("upload_params") if isinstance(info, Mapping) else None
        if not upload_url or not isinstance(upload_params, Mapping):
            raise ParseError("Canvas 文件上传预检响应缺少 upload_url / upload_params。")
        with open(file_path, "rb") as handle:
            upload = self._session.post(
                upload_url,
                data=dict(upload_params),
                files={"file": (name, handle, content_type)},
                timeout=UPLOAD_TIMEOUT,
            )
        self._raise_for_status(upload)
        uploaded = File.from_json(self._json(upload))
        if uploaded.id is None:
            raise ParseError(f"文件 {name} 上传后未返回文件 id，无法用于提交。")
        return uploaded

    def submit_assignment(
        self,
        course_id: int | str,
        assignment_id: int | str,
        *,
        file_paths: Sequence[Path | str] = (),
        text: str | None = None,
        url: str | None = None,
        dry_run: bool = False,
    ) -> Submission | dict[str, Any]:
        """提交作业（本人提交，支持文件 / 文本 / 链接三种类型之一）。

        文件提交先按 Canvas 官方流程把文件上传到课程文件区
        （:meth:`upload_course_file`），再 ``POST
        /courses/:cid/assignments/:aid/submissions`` 附带 ``file_ids``；
        文本 / 链接提交分别对应 ``online_text_entry`` / ``online_url``。

        Args:
            course_id / assignment_id: 课程与作业 id。
            file_paths: 本地文件路径列表（``online_upload``）。
            text: 文本提交内容（``online_text_entry``）。
            url: 链接提交 URL（``online_url``）。
            dry_run: 只做预检（作业存在、未锁定、类型允许、文件可读），
                返回描述字典，**不发提交请求也不上传文件**。

        Returns:
            真提交返回 :class:`Submission`；``dry_run=True`` 返回计划字典。

        Raises:
            ActionError: 提交方式给了多种或没给、作业已锁定、作业不
                支持所选提交类型、文件不可读，或 Canvas 拒绝提交。
        """
        wanted = {
            SUBMISSION_TYPE_UPLOAD: bool(file_paths),
            SUBMISSION_TYPE_TEXT: bool(text and text.strip()),
            SUBMISSION_TYPE_URL: bool(url and url.strip()),
        }
        chosen = [kind for kind, hit in wanted.items() if hit]
        if len(chosen) != 1:
            raise ActionError(
                "提交方式必须且只能给一种：文件（file_paths）/ 文本（text）/ 链接（url）。"
            )
        kind = chosen[0]
        assignment = self.get_assignment(course_id, assignment_id)
        if assignment.locked_for_user:
            raise ActionError(f"作业「{assignment.name}」已锁定，无法提交。")
        allowed = assignment.submission_types
        if allowed and kind not in allowed:
            raise ActionError(
                f"作业「{assignment.name}」不支持 {kind} 提交；"
                f"允许的类型：{'、'.join(allowed)}。"
            )
        files = [Path(path) for path in file_paths]
        for path in files:
            if not path.is_file():
                raise ActionError(f"文件不存在或不是普通文件：{path}")
        if dry_run:
            return {
                "dry_run": True,
                "assignment_id": assignment.id,
                "assignment": assignment.name,
                "submission_type": kind,
                "files": [path.name for path in files],
                "text_preview": (text or "")[:100],
                "url": url,
                "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
            }
        pairs: list[tuple[str, str]] = [("submission[submission_type]", kind)]
        if kind == SUBMISSION_TYPE_UPLOAD:
            uploaded = [self._upload_for_submission(course_id, path) for path in files]
            pairs.extend(
                ("submission[file_ids][]", str(item.id)) for item in uploaded if item.id
            )
        elif kind == SUBMISSION_TYPE_TEXT:
            pairs.append(("submission[body]", text or ""))
        else:
            pairs.append(("submission[url]", url or ""))
        response = self._post(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions",
            data=pairs,
        )
        return Submission.from_json(self._json(response))

    def get_submission(self, course_id: int | str, assignment_id: int | str) -> Submission:
        """读取本人在某作业上的当前提交（``GET .../submissions/self``）。"""
        return Submission.from_json(
            self._json(
                self._get(
                    f"/courses/{course_id}/assignments/{assignment_id}/submissions/self"
                )
            )
        )

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
    "UPLOAD_TIMEOUT",
    "CanvasClient",
    "resolve_base_url",
    "resolve_token",
    "token_file_path",
]
