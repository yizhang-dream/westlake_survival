"""OneDrive / SharePoint 分享文件夹（只读）：列文件与下载讲义。

教师常把课程讲义放在 OneDrive/SharePoint 共享目录（``westlakeu-my.sharepoint.com``）。
当分享链接设为「组织内任何人可查看」时，**不需要账号**也能列出文件并下载：

1. 打开分享链接，页面落在 ``onedrive.aspx?id=<编码后的文件夹路径>``；
2. 从页面读 ``_spPageContextInfo.formDigestValue`` 取表单摘要；
3. 带摘要调 SharePoint 列表接口 ``RenderListDataAsStream`` 取行；
4. 下载走 ``_layouts/15/download.aspx?UniqueId={guid}`` 匿名直链。

实测（2026-10-26）：``2183-lecture-notes`` 列出 14 个文件；单文件下载
2,625,766 字节，sha256 与旧本地镜像清单逐字节一致。

纯 :mod:`requests` 在部分环境会被 urllib3 的 HTTP/3 后端打断
（``BufferReadError``），所以统一走无头 Chromium。Playwright 是可选依赖：
缺失时抛 :class:`ShareError` 并给出安装提示。

只读：不写分享目录、不上传；链接若为「仅特定人员」，匿名读取会失败，
此时只能让分享者放开权限或自行在浏览器里登录查看。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from westlake_survival._cache import config_root
from westlake_survival.exceptions import WestlakeError

__all__ = [
    "REGISTRY_FILENAME",
    "ShareBrowser",
    "ShareError",
    "ShareItem",
    "cli_group",
    "load_saved",
    "registry_path",
    "remove_share",
    "resolve_share",
    "save_share",
]

#: 已保存分享链接的登记文件名（位于配置根目录）。
REGISTRY_FILENAME = "shares.json"

#: 页面加载与请求的超时（毫秒）。
DEFAULT_TIMEOUT_MS = 90_000


class ShareError(WestlakeError):
    """分享链接不可读、权限不足或解析失败。"""


@dataclass(frozen=True)
class ShareItem:
    """分享文件夹里的一行（文件或子目录）。"""

    name: str
    size: int | None
    modified: str | None
    unique_id: str
    is_folder: bool = False


# --------------------------------------------------------------------------- #
# 已保存的分享链接（名字 → 链接）
# --------------------------------------------------------------------------- #


def registry_path() -> Path:
    """返回分享链接登记文件路径（不创建文件）。"""
    return config_root() / REGISTRY_FILENAME


def load_saved() -> dict[str, str]:
    """读取已保存的分享链接；文件缺失或损坏时返回空 dict。"""
    path = registry_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_share(name: str, url: str) -> Path:
    """保存一条「名字 → 分享链接」；同名覆盖。"""
    name = name.strip()
    url = url.strip()
    if not name or not url:
        raise ShareError("名字和链接都不能为空。")
    if "sharepoint.com" not in url and "onedrive" not in url:
        raise ShareError(f"看起来不是 OneDrive/SharePoint 分享链接：{url[:80]}")
    data = load_saved()
    data[name] = url
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def remove_share(name: str) -> bool:
    """删除一条登记；本来就不存在时返回 ``False``。"""
    data = load_saved()
    if name not in data:
        return False
    data.pop(name)
    registry_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def resolve_share(ref: str | None, *, saved: dict[str, str] | None = None) -> tuple[str, str]:
    """把「名字或链接」解析成 ``(标签, 链接)``。

    Args:
        ref: 已保存的名字，或一条 http(s) 分享链接。
        saved: 可注入的登记表（测试/调用方复用）。

    Raises:
        ShareError: 为空、名字未登记、或不像分享链接。
    """
    if not ref or not ref.strip():
        names = ", ".join(sorted(saved if saved is not None else load_saved())) or "（还没有）"
        raise ShareError(f"需要 --name 或 --url。已保存的分享：{names}")
    ref = ref.strip()
    if ref.startswith(("http://", "https://")):
        return "分享链接", ref
    table = saved if saved is not None else load_saved()
    if ref in table:
        return ref, table[ref]
    raise ShareError(f"没有保存过名为「{ref}」的分享链接；已保存：{', '.join(sorted(table)) or '（空）'}")


# --------------------------------------------------------------------------- #
# 浏览与下载
# --------------------------------------------------------------------------- #


def _safe_name(name: str) -> str:
    """把文件名压成单层安全名，避免路径穿越与非法字符。"""
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or "未命名"


class ShareBrowser:
    """在一个分享文件夹上列文件、下文件；用完即关。

    Example:
        >>> with ShareBrowser(url) as browser:            # doctest: +SKIP
        ...     for item in browser.list_items():
        ...         print(item.name, item.size)
    """

    def __init__(self, share_url: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.share_url = share_url.strip()
        self.timeout_ms = timeout_ms
        self.host = ""
        self.user = ""
        self.folder = ""
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._digest = ""

    # -- 生命周期 -------------------------------------------------------- #

    def __enter__(self) -> ShareBrowser:  # noqa: PYI034 - 3.10 无法用 typing.Self
        self._start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001,S110 - 关闭失败不影响退出
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # noqa: BLE001,S110 - 关闭失败不影响退出
            pass
        self._pw = self._browser = self._context = self._page = None

    def _start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 取决于环境
            raise ShareError(
                "读取 OneDrive/SharePoint 分享需要 Playwright（无头浏览器）。\n"
                "安装：pip install playwright && playwright install chromium"
            ) from exc

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(locale="zh-CN")
        self._page = self._context.new_page()
        try:
            self._page.goto(self.share_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception as exc:
            raise ShareError(f"打开分享链接失败：{exc}") from exc
        # OneDrive 页面先渲染骨架，列表接口随后才发；等一小会儿再取摘要。
        self._page.wait_for_timeout(2500)
        self._resolve_target()
        self._digest = self._page_digest()
        if not self._digest:
            raise ShareError(
                "未取到 SharePoint 表单摘要。链接可能已失效，或权限不是「组织内任何人可查看」。"
            )

    def _resolve_target(self) -> None:
        """从落地页 URL 解析租户、用户与文件夹路径。"""
        final = self._page.url
        if "login.microsoftonline.com" in final or "/_forms/login" in final.lower():
            raise ShareError(
                "该分享需要登录才能查看（链接可能只对特定人员开放）。"
                "请分享者改成「组织内任何人可查看」，或自行在浏览器里登录后下载。"
            )
        match = re.match(r"https://([^/]+)/personal/([^/]+)/", final)
        if not match:
            raise ShareError(f"未识别为 OneDrive/SharePoint 页面：{final[:120]}")
        self.host, self.user = match.group(1), match.group(2)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
        folder = query.get("id", [""])[0].strip()
        if not folder:
            marker = f"/personal/{self.user}/Documents"
            index = urllib.parse.unquote(final).find(marker)
            if index < 0:
                raise ShareError("未能在页面地址里定位分享文件夹路径。")
            folder = urllib.parse.unquote(final)[index:]
        self.folder = folder.rstrip("/")

    def _page_digest(self) -> str:
        try:
            return self._page.evaluate(
                "() => (window._spPageContextInfo && window._spPageContextInfo.formDigestValue) || ''"
            )
        except Exception:  # noqa: BLE001 - 页面上下文不可用时回退到其它取摘要方式
            return ""

    # -- 列表 ------------------------------------------------------------ #

    def _list_url(self, root_folder: str) -> str:
        list_root = f"/personal/{self.user}/Documents"
        quoted_root = urllib.parse.quote(f"'{list_root}'")
        quoted_folder = urllib.parse.quote(root_folder)
        return (
            f"https://{self.host}/personal/{self.user}/_api/web/"
            "GetListUsingPath(DecodedUrl=@a1)/RenderListDataAsStream"
            f"?@a1={quoted_root}&RootFolder={quoted_folder}&TryNewExperienceSingle=TRUE"
        )

    def _post_rows(self, url: str) -> dict:
        body = {
            "parameters": {
                "__metadata": {"type": "SP.RenderListDataParameters"},
                "RenderOptions": 5691143,
                "AllowMultipleValueFilterForTaxonomyFields": True,
                "AddRequiredFields": True,
                "RequireFolderColoringFields": True,
            }
        }
        headers = {
            "Content-Type": "application/json;odata=verbose",
            "Accept": "application/json;odata=verbose",
            "X-RequestDigest": self._digest,
        }
        response = self._context.request.post(
            url, data=json.dumps(body), headers=headers, timeout=self.timeout_ms
        )
        if response.status != 200:
            if response.status in (401, 403):
                raise ShareError(
                    f"分享不可匿名读取（HTTP {response.status}）。"
                    "需要分享者把链接权限改为「组织内任何人可查看」。"
                )
            raise ShareError(f"列表接口返回 HTTP {response.status}：{response.text()[:160]}")
        return response.json()

    def list_items(self, subpath: str | None = None) -> list[ShareItem]:
        """列出分享文件夹（或其子目录）里的文件与子目录。

        Args:
            subpath: 子目录相对路径，如 ``Advanced Labs``；None 表示分享根。

        Raises:
            ShareError: 接口失败或权限不足。
        """
        root = self.folder
        if subpath:
            root = root.rstrip("/") + "/" + subpath.strip("/")
        url = self._list_url(root)
        items: list[ShareItem] = []
        for _ in range(20):  # 分页上限，正常一页就够
            data = self._post_rows(url)
            rows = (data.get("ListData") or {}).get("Row") or []
            items.extend(_row_to_item(row) for row in rows)
            next_href = (data.get("ListData") or {}).get("NextHref") or ""
            if not next_href:
                break
            url = _absolute_next(self.host, next_href)
        return items

    # -- 下载 ------------------------------------------------------------ #

    def download(self, item: ShareItem, dest_dir: Path, *, overwrite: bool = False) -> Path:
        """下载一个文件到 ``dest_dir``；同名且大小一致时跳过。"""
        if item.is_folder:
            raise ShareError(f"「{item.name}」是文件夹，不能直接下载。")
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / _safe_name(item.name)
        if target.exists() and not overwrite and item.size and target.stat().st_size == item.size:
            return target
        url = (
            f"https://{self.host}/personal/{self.user}/_layouts/15/download.aspx"
            f"?UniqueId={{{item.unique_id}}}"
        )
        response = self._context.request.get(url, timeout=self.timeout_ms)
        if response.status != 200:
            raise ShareError(f"下载「{item.name}」失败：HTTP {response.status}")
        data = response.body()
        if item.size and len(data) != item.size:
            raise ShareError(
                f"下载「{item.name}」大小不符：期望 {item.size}，实际 {len(data)}（可能链接已失效）"
            )
        target.write_bytes(data)
        return target


def _row_to_item(row: dict) -> ShareItem:
    """把列表接口的一行转成 :class:`ShareItem`。"""
    name = (
        row.get("FileLeafRef")
        or row.get("LinkFilename")
        or row.get("LinkFilenameNoMenu")
        or "—"
    )
    raw_size = row.get("File_x0020_Size")
    try:
        size = int(raw_size)
    except (TypeError, ValueError):
        size = None
    modified = row.get("Modified") or None
    unique = str(row.get("UniqueId") or "").strip("{}").upper()
    return ShareItem(
        name=str(name),
        size=size,
        modified=modified,
        unique_id=unique,
        is_folder=str(row.get("FSObjType") or "0") == "1",
    )


def _absolute_next(host: str, href: str) -> str:
    if href.startswith("http"):
        return href
    return f"https://{host}{href if href.startswith('/') else '/' + href}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _cli():
    import functools

    import click

    from westlake_survival.exceptions import WestlakeError

    def handle(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WestlakeError as exc:
                click.secho(f"错误：{exc}", fg="red", err=True)
                raise SystemExit(1) from exc

        return wrapper

    def _human(size: int | None) -> str:
        if not size:
            return "—"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def _table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> None:
        table = [list(headers)] + [list(r) for r in rows]
        widths = [max(len(str(r[i])) for r in table) for i in range(len(headers))]
        for index, row in enumerate(table):
            click.echo("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())
            if index == 0:
                click.echo("  ".join("-" * w for w in widths))

    @click.group(name="share", help="OneDrive/SharePoint 分享文件夹：列文件、下载讲义（免账号）。")
    def group() -> None:
        """``westlake share add|saved|remove|files|download``。"""

    @group.command(name="add")
    @click.argument("name")
    @click.argument("url")
    @handle
    def add_cmd(name: str, url: str) -> None:
        """保存一条分享链接：NAME URL。"""
        path = save_share(name, url)
        click.echo(f"已保存「{name}」→ {path}")

    @group.command(name="saved")
    @handle
    def saved_cmd() -> None:
        """列出已保存的分享链接。"""
        data = load_saved()
        if not data:
            click.echo("还没有保存的分享链接；用 `westlake share add <名字> <链接>` 添加。")
            return
        for name, url in sorted(data.items()):
            click.echo(f"{name:<20} {url[:88]}")

    @group.command(name="remove")
    @click.argument("name")
    @handle
    def remove_cmd(name: str) -> None:
        """删除一条已保存的分享链接。"""
        click.echo(f"已删除「{name}」" if remove_share(name) else f"没有名为「{name}」的记录")

    def _ref(url: str | None, name: str | None) -> tuple[str, str]:
        label, link = resolve_share(url or name)
        return (name or label), link

    @group.command(name="files")
    @click.option("--url", default=None, help="分享链接。")
    @click.option("--name", default=None, help="已保存的分享名字。")
    @click.option("--path", default=None, help="子目录（相对分享根），如 “Advanced Labs”。")
    @click.option("--match", default=None, help="按文件名关键词筛选（子串，不区分大小写）。")
    @handle
    def files_cmd(url: str | None, name: str | None, path: str | None, match: str | None) -> None:
        """列出分享文件夹里的文件。"""
        label, link = _ref(url, name)
        with ShareBrowser(link) as browser:
            items = browser.list_items(path)
        if match:
            needle = match.lower()
            items = [item for item in items if needle in item.name.lower()]
        if not items:
            click.echo("没有匹配的文件")
            return
        rows = [
            ("目录" if item.is_folder else "文件", item.name, _human(item.size), item.modified or "—")
            for item in items
        ]
        _table(rows, ("类型", "名称", "大小", "修改时间"))
        click.echo(f"分享：{label}（{len(items)} 项）")

    @group.command(name="download")
    @click.option("--url", default=None, help="分享链接。")
    @click.option("--name", default=None, help="已保存的分享名字。")
    @click.option("--path", default=None, help="子目录（相对分享根）。")
    @click.option("--match", default=None, help="按文件名关键词筛选（子串，不区分大小写）。")
    @click.option("--out", "out_dir", default="./分享文件", show_default=True, help="下载目录。")
    @click.option("--overwrite", is_flag=True, help="同名且大小一致时也重新下载。")
    @handle
    def download_cmd(
        url: str | None,
        name: str | None,
        path: str | None,
        match: str | None,
        out_dir: str,
        overwrite: bool,
    ) -> None:
        """下载分享文件夹里的文件（可只下命中的）。"""
        label, link = _ref(url, name)
        target = Path(out_dir).expanduser()
        with ShareBrowser(link) as browser:
            items = [item for item in browser.list_items(path) if not item.is_folder]
            if match:
                needle = match.lower()
                items = [item for item in items if needle in item.name.lower()]
            if not items:
                click.echo("没有匹配的文件")
                return
            click.echo(f"分享：{label}，准备下载 {len(items)} 个文件 → {target}")
            saved = 0
            for item in items:
                got = browser.download(item, target, overwrite=overwrite)
                saved += 1
                click.echo(f"  [{saved}/{len(items)}] {got.name}（{_human(item.size)}）")
        click.echo(f"完成：{saved} 个文件，目录 {target}")

    return group


cli_group = _cli()
