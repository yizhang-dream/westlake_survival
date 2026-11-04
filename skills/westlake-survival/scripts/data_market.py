"""Read the portal data market with the locally configured account.

CLI output contains counts, field names and catalog metadata. Use MarketClient
in-process to select personal business fields without printing entire records.
"""
from __future__ import annotations

import argparse
import json
from urllib.parse import parse_qs, urlsplit

import requests

from westlake_survival import iam
from westlake_survival.discovery import direct_session
from westlake_survival.sso import read_credentials

BASE = "https://my.westlake.edu.cn"
APP = "shujushiji3173474984560511355"
PREFIX = f"/service/{APP}/shishengjibenxinxi"
USER_INFO = "/service/portal/main/pc-user-info"
CURRENT_ACCOUNT = "CURRENT_ACCOUNT"
FILTERS = {
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
ALLOWED_REQUESTS = {
    ("GET", USER_INFO),
    ("GET", "/service/ctp-user/auth/refresh-token"),
    ("GET", PREFIX + "/microflow/MFSERVICEY3eDkR"),
    ("POST", PREFIX + "/microflow/MFSERVICEA3oicu"),
} | {("POST", f"{PREFIX}/filter-plan/{APP}/{entity}/{plan}")
     for entity, plan, _ in FILTERS.values()}


class MarketError(RuntimeError):
    """A failure described without credentials, callback URLs or response bodies."""


def _captcha_guard(response, *args, **kwargs):
    if urlsplit(response.url).path == "/idp/authn/verifyCodeIsNeed":
        need = response.json()
        data = need.get("data")
        signals = [need.get("result"), data if isinstance(data, bool) else None,
                   data.get("result") if isinstance(data, dict) else None]
        if any(value is True for value in signals) or not any(value is False for value in signals):
            raise MarketError("IAM 验证码状态未明确关闭；已停止，未提交密码认证。请在官方页面处理后重试。")
    return response


def _account_values(value, account):
    if isinstance(value, dict):
        return {key: _account_values(item, account) for key, item in value.items()}
    if isinstance(value, list):
        return [_account_values(item, account) for item in value]
    return account if value == CURRENT_ACCOUNT else value


class MarketClient:
    """One in-memory session; query templates always use the configured account."""

    def __init__(self):
        self.session = direct_session()
        self.session.headers.update({"Accept": "application/json", "Referer": BASE + "/main/portal"})
        self._account = ""

    def __enter__(self):
        try:
            self._login()
        except Exception:
            self.session.close()
            raise
        return self

    def __exit__(self, *args):
        self.session.close()

    def _json(self, method, path, **kwargs):
        if (method, path) not in ALLOWED_REQUESTS:
            raise MarketError("请求不在数据市集只读白名单中。")
        try:
            response = self.session.request(method, BASE + path, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise MarketError("门户请求失败或未返回 JSON；检查校园网/VPN，勿连续重试登录。") from None

    def _user_info(self):
        result = self._json("GET", USER_INFO, params={"ioa": "0", "locale": "zh_CN"})
        return result.get("data", {}).get("content") or {}

    def _login(self):
        self._account, password = read_credentials()
        info = self._user_info()
        if info.get("USER_INFO_MAP"):
            return
        redirect = info.get("redirectUrl", "")
        parsed = urlsplit(redirect)
        if parsed.scheme != "https" or parsed.hostname != "iam.westlake.edu.cn":
            raise MarketError("门户未返回官方 IAM 入口；停止登录，请重新检查官网入口。")
        callbacks = []

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

    def _page(self, kind, number, page_size):
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
                    "searchParam": {}, "logicalOperator": "AND", "sortSettings": [],
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

    def fetch(self, kind, *, page_size=100):
        """Return content/pageInfo, following every page while preserving account filters."""
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


def _label(value):
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        if isinstance(decoded, dict):
            return decoded.get("zh_CN") or decoded.get("en") or ""
    return value


def summarize(kind, data, *, counts_only=False):
    content = data["content"]
    result = {"query": kind}
    if isinstance(content, list):
        result.update({"count": len(content), "fields": list(content[0]) if content and isinstance(content[0], dict) else []})
        if kind == "catalog" and not counts_only:
            result["entries"] = [{
                "title": _label(row.get("dataTitle")),
                "theme": [_label(item.get("name")) for item in row.get("theme___displayname", [])],
                "department": [item.get("name") for item in row.get("department___displayname", [])],
                "frequency": row.get("frequency"),
            } for row in content]
    elif isinstance(content, dict):
        result.update({"field_count": len(content), "fields": list(content)})
    else:
        raise MarketError("业务响应类型变化；停止输出，请核对官方页面。")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", choices=KINDS)
    parser.add_argument("--summary", action="store_true", help="目录也仅输出数量和字段名")
    parser.add_argument("--page-size", type=int, default=100, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    try:
        with MarketClient() as client:
            data = client.fetch(args.query, page_size=args.page_size)
        print(json.dumps(summarize(args.query, data, counts_only=args.summary), ensure_ascii=False, indent=2))
    except MarketError as exc:
        parser.exit(1, str(exc) + "\n")
    except Exception:
        parser.exit(1, "数据市集查询失败；先运行 westlake doctor 检查本机环境与账号配置。\n")


if __name__ == "__main__":
    main()
