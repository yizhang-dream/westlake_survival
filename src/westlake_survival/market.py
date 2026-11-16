"""门户数据市集：数据目录与本人档案/履历/已修课程/荣誉/社团/志愿只读接入。

核心安全边界：
1. 请求严格限制在 :data:`ALLOWED_REQUESTS` 只读白名单内；
2. 遇到 IAM 验证码状态未明确关闭时立即抛 :class:`MarketError` 停止，绝不提交密码；
3. 账号筛选锁定 :data:`CURRENT_ACCOUNT`（当前本机已配置账号），不接受外部传入他人学号；
4. 会话 Cookie、密码与 OAuth 回跳参数仅驻留进程内存，绝不落盘、绝不进错误消息；
5. CLI 与 MCP 默认只输出 :func:`summarize` 摘要（目录元数据或条数+字段名），
   需要具体业务字段时在 Python 进程内使用 ``with MarketClient() as client:`` 按需筛选字段。
"""
from __future__ import annotations

import argparse
import functools
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import click
import requests

from westlake_survival import iam
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import WestlakeError
from westlake_survival.sso import read_credentials

__all__ = [
    "ALLOWED_REQUESTS",
    "BASE",
    "CURRENT_ACCOUNT",
    "FILTERS",
    "KINDS",
    "MarketClient",
    "MarketError",
    "PREFIX",
    "USER_INFO",
    "cli_group",
    "fetch_summary",
    "summarize",
]

BASE = "https://my.westlake.edu.cn"
APP = "shujushiji3173474984560511355"
PREFIX = f"/service/{APP}/shishengjibenxinxi"
USER_INFO = "/service/portal/main/pc-user-info"
CURRENT_ACCOUNT = "CURRENT_ACCOUNT"
FILTERS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "catalog": ("data-directory", "-2878502347698636847", {
        "7badb8ab-629e-484b-963b-8f13f769c81c": [{"index": 0, "value": ""}],
        "f34fcff8-018f-40da-9935-b0945eb2c92a": [{"index": 0, "value": ""}],
    }),
    "courses": ("yixiukecheng", "817016326845050913", {
        "a39a345d-5a5e-4f1f-a217-57c532207147": [{"index": 0, "value": CURRENT_ACCOUNT}],
        "4d9ca992-d44f-44ba-9eea-9af28d831328": [{"index": 0, "value": ""}],
    }),
    "honors": ("yihuorongyu", "-5282470682246720647", {}),
    "clubs": ("xueshengshetuan", "4554022627636571168", {}),
    "volunteer": ("zhiyuanfuwu", "2112765409447681399", {
        "d535dbc3-277e-40e9-a256-9fd6fc4c662c": [],
    }),
}
KINDS = ("catalog", "profile", "resume", "courses", "honors", "clubs", "volunteer")
ALLOWED_REQUESTS: set[tuple[str, str]] = {
    ("GET", USER_INFO),
    ("GET", "/service/ctp-user/auth/refresh-token"),
    ("GET", PREFIX + "/microflow/MFSERVICEY3eDkR"),
    ("POST", PREFIX + "/microflow/MFSERVICEA3oicu"),
} | {
    ("POST", f"{PREFIX}/filter-plan/{APP}/{entity}/{plan}")
    for entity, plan, _ in FILTERS.values()
}

_KIND_LABELS: dict[str, str] = {
    "catalog": "数据目录",
    "profile": "本人基本/学籍档案",
    "resume": "本人个人履历",
    "courses": "本人已修课程",
    "honors": "本人已获荣誉",
    "clubs": "本人学生社团记录",
    "volunteer": "本人志愿服务",
}


class MarketError(WestlakeError):
    """数据市集异常（错误信息绝不含凭据、回调 URL 或原始响应体）。"""


def _captcha_guard(response, *args, **kwargs):
    if urlsplit(response.url).path == "/idp/authn/verifyCodeIsNeed":
        need = response.json()
        data = need.get("data")
        signals = [
            need.get("result"),
            data if isinstance(data, bool) else None,
            data.get("result") if isinstance(data, dict) else None,
        ]
        if any(value is True for value in signals) or not any(value is False for value in signals):
            raise MarketError("IAM 验证码状态未明确关闭；已停止，未提交密码认证。请在官方页面处理后重试。")
    return response


def _account_values(value: Any, account: str) -> Any:
    if isinstance(value, dict):
        return {key: _account_values(item, account) for key, item in value.items()}
    if isinstance(value, list):
        return [_account_values(item, account) for item in value]
    return account if value == CURRENT_ACCOUNT else value


class MarketClient:
    """进程内单次会话客户端；查询模板始终绑定当前本机配置账号。"""

    def __init__(self) -> None:
        self.session = direct_session()
        self.session.headers.update({"Accept": "application/json", "Referer": BASE + "/main/portal"})
        self._account = ""

    def __enter__(self) -> "MarketClient":
        try:
            self._login()
        except Exception:
            self.session.close()
            raise
        return self

    def __exit__(self, *args) -> None:
        self.session.close()

    def _json(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        if (method, path) not in ALLOWED_REQUESTS:
            raise MarketError("请求不在数据市集只读白名单中。")
        try:
            response = self.session.request(method, BASE + path, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise MarketError("门户请求失败或未返回 JSON；检查校园网/VPN，勿连续重试登录。") from None

    def _user_info(self) -> dict[str, Any]:
        result = self._json("GET", USER_INFO, params={"ioa": "0", "locale": "zh_CN"})
        return result.get("data", {}).get("content") or {}

    def _login(self) -> None:
        try:
            self._account, password = read_credentials()
        except Exception:
            raise MarketError("未配置统一凭据；请先 westlake setup 或在网页「设置」页配置。") from None
        info = self._user_info()
        if info.get("USER_INFO_MAP"):
            return
        redirect = info.get("redirectUrl", "")
        parsed = urlsplit(redirect)
        if parsed.scheme != "https" or parsed.hostname != "iam.westlake.edu.cn":
            raise MarketError("门户未返回官方 IAM 入口；停止登录，请重新检查官网入口。")
        callbacks: list[str] = []

        def remember_callback(response, *args, **kwargs):
            location = urlsplit(response.url)
            if location.hostname == "my.westlake.edu.cn" and location.path == "/login/third-auth/code":
                callbacks.append(response.url)
            return response

        self.session.hooks["response"].extend([_captcha_guard, remember_callback])
        try:
            iam.login_for(redirect, self._account, password, session=self.session)
        except MarketError:
            raise
        except Exception:
            raise MarketError("统一认证未完成；检查本机账号配置或在官方页面处理验证码，勿反复尝试密码。") from None
        finally:
            self.session.hooks["response"].remove(_captcha_guard)
            self.session.hooks["response"].remove(remember_callback)
        if not callbacks:
            raise MarketError("未取得门户 OAuth 回跳；停止，不重复提交登录。")
        query = parse_qs(urlsplit(callbacks[-1]).query)
        params = {key: query.get(key, [""])[0] for key in ("code", "redirectUri")}
        if not all(params.values()):
            raise MarketError("门户 OAuth 回跳参数不完整；停止会话交换。")
        exchanged = self._json("GET", "/service/ctp-user/auth/refresh-token", params=params)
        if exchanged.get("code") != "BOOT_0000" or not self._user_info().get("USER_INFO_MAP"):
            raise MarketError("门户会话交换失败；未取得有效的本人登录态。")

    def _page(self, kind: str, number: int, page_size: int) -> dict[str, Any]:
        if kind == "profile":
            method, path, payload = "GET", PREFIX + "/microflow/MFSERVICEY3eDkR", None
        elif kind == "resume":
            method, path, payload = "POST", PREFIX + "/microflow/MFSERVICEA3oicu", self._account
        else:
            entity, plan, expressions = FILTERS[kind]
            method, path = "POST", f"{PREFIX}/filter-plan/{APP}/{entity}/{plan}"
            payload = {
                "filterPlanGuids": [plan],
                "searchParams": {
                    "searchParam": {},
                    "logicalOperator": "AND",
                    "sortSettings": [],
                    "expressionValues": _account_values(expressions, self._account),
                    "one2OneEntityRelationsV2": [],
                },
                "pageInfo": {"pageNumber": number, "pageSize": page_size, "total": 0, "needTotal": True},
            }
        result = self._json(method, path, **({"json": payload} if method == "POST" else {}))
        if result.get("code") != "BOOT_0000" or not isinstance(result.get("data"), dict):
            raise MarketError("数据市集查询未成功；可能是权限、会话或页面版本变化，请核对官方页面。")
        data = result["data"]
        if "content" not in data or data["content"] is None:
            raise MarketError("数据市集响应缺少业务内容；不将其视为空记录。")
        return data

    def fetch(self, kind: str, *, page_size: int = 100) -> dict[str, Any]:
        """返回 content/pageInfo；自动跟随全部页并核对总数。"""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if not self._account:
            raise MarketError("请在 with MarketClient() 上下文中调用。")
        first = self._page(kind, 1, page_size)
        if kind not in FILTERS:
            return first
        if not isinstance(first["content"], list):
            raise MarketError("列表接口未返回列表；请核对页面版本。")
        rows = list(first["content"])
        page_info = first.get("pageInfo") or {}
        if not all(isinstance(page_info.get(key), int) for key in ("pages", "total")):
            raise MarketError("列表接口缺少分页总数；不把当前页当作全量。")
        for number in range(2, page_info["pages"] + 1):
            following = self._page(kind, number, page_size)
            if not isinstance(following["content"], list) or not following["content"]:
                raise MarketError("分页中途返回空页；未取得全量，请稍后核对。")
            rows.extend(following["content"])
        if len(rows) != page_info["total"]:
            raise MarketError("实际条数与分页总数不一致；未确认全量。")
        return {**first, "content": rows}


def _label(value: Any) -> Any:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        if isinstance(decoded, dict):
            return decoded.get("zh_CN") or decoded.get("en") or ""
    return value


def summarize(kind: str, data: dict[str, Any], *, counts_only: bool = False) -> dict[str, Any]:
    """将业务返回转换为仅含条数/字段名/目录元数据的脱敏概要。"""
    content = data["content"]
    result: dict[str, Any] = {"query": kind}
    if isinstance(content, list):
        result.update({
            "count": len(content),
            "fields": list(content[0]) if content and isinstance(content[0], dict) else [],
        })
        if kind == "catalog" and not counts_only:
            result["entries"] = [
                {
                    "title": _label(row.get("dataTitle")),
                    "theme": [_label(item.get("name")) for item in row.get("theme___displayname", [])],
                    "department": [item.get("name") for item in row.get("department___displayname", [])],
                    "frequency": row.get("frequency"),
                }
                for row in content
            ]
    elif isinstance(content, dict):
        result.update({"field_count": len(content), "fields": list(content)})
    else:
        raise MarketError("业务响应类型变化；停止输出，请核对官方页面。")
    return result


def fetch_summary(
    kind: str, *, counts_only: bool = False, page_size: int = 100
) -> dict[str, Any]:
    """在单次内存会话中拉取并汇总数据市集查询（不输出原始个人字段）。"""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    with MarketClient() as client:
        data = client.fetch(kind, page_size=page_size)
    return summarize(kind, data, counts_only=counts_only)


# --------------------------------------------------------------------------- #
# CLI：westlake market <kind>
# --------------------------------------------------------------------------- #
def _handle_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WestlakeError as exc:
            click.secho(f"错误：{exc}", fg="red", err=True)
            raise SystemExit(1) from exc

    return wrapper


def _print_summary(kind: str, summary: dict[str, Any]) -> None:
    label = _KIND_LABELS.get(kind, kind)
    if kind == "catalog" and "entries" in summary:
        entries = summary["entries"]
        click.secho(f"门户数据市集目录（共 {summary.get('count', len(entries))} 项）：", fg="cyan", bold=True)
        for idx, item in enumerate(entries, 1):
            themes = "、".join(t for t in (item.get("theme") or []) if t) or "—"
            depts = "、".join(d for d in (item.get("department") or []) if d) or "—"
            freq = item.get("frequency") or "—"
            click.echo(f"  {idx:>2}. {item.get('title') or '—'}  [{themes}]  {depts}  ({freq})")
        if summary.get("fields"):
            click.echo(f"\n字段（{len(summary['fields'])}）：{', '.join(summary['fields'])}")
        return

    click.secho(f"门户数据市集 · {label}（{kind}）", fg="cyan", bold=True)
    if "count" in summary:
        click.echo(f"  记录条数：{summary['count']}")
    if "field_count" in summary:
        click.echo(f"  顶层字段数：{summary['field_count']}")
    fields = summary.get("fields") or []
    click.echo(f"  字段列表（{len(fields)}）：{', '.join(fields) if fields else '—'}")
    click.echo("  提示：CLI 默认只输出条数与字段名以避免回显证件/联系方式；如需读取具体字段，请在 Python 中使用 MarketClient。")


@click.group(
    name="market",
    help="门户数据市集：数据目录与本人档案/履历/已修课程/荣誉/社团/志愿概要（只读）。",
)
def cli_group() -> None:
    """门户数据市集命令组（仅输出脱敏概要）。"""


def _register_kind_command(kind: str, help_text: str) -> None:
    is_catalog = kind == "catalog"

    @click.option("--page-size", type=click.IntRange(1, 100), default=100, show_default=True, help="分页大小（1..100）。")
    @click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出脱敏概要。")
    @_handle_errors
    def _cmd(page_size: int, as_json: bool, summary: bool = False) -> None:
        result = fetch_summary(kind, counts_only=summary, page_size=page_size)
        if as_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            return
        _print_summary(kind, result)

    if is_catalog:
        _cmd = click.option(
            "--summary", "summary", is_flag=True, help="仅输出目录总数与字段名，不展开条目清单。"
        )(_cmd)
    _cmd.__doc__ = help_text
    cli_group.command(name=kind, help=help_text)(_cmd)


for _k, _desc in (
    ("catalog", "当前账号可见的数据集目录（支持 --summary）。"),
    ("profile", "本人基本/学籍档案概要（顶层字段数与字段名）。"),
    ("resume", "本人个人履历概要（条数与字段名）。"),
    ("courses", "本人已修课程概要（条数与字段名）。"),
    ("honors", "本人已获荣誉概要（条数与字段名）。"),
    ("clubs", "本人学生社团记录概要（条数与字段名）。"),
    ("volunteer", "本人志愿服务概要（条数与字段名）。"),
):
    _register_kind_command(_k, _desc)
del _k, _desc
