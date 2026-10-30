"""高性能计算中心（HPC）公开信息：集群队列配置、手册与入口。

数据源
======
``hpc.westlake.edu.cn`` 主站是 Vue SPA，集群/队列表**不在 DOM 里**，而是
编译进 ``js/app.<hash>.js`` 的渲染函数字符串（``t("td",[e._v("amd-ep2")])``
形态）。本模块直接抓 bundle 并用字符串抽取还原表格：

* ``Computing Resource`` 表：每队列 = 队列名 + 节点数 + (CPU/Memory/NVME) 三行配置；
* 集群名（科学工程计算 / 人工智能 / Cryo-EM）与「用户手册」路由同理抽取。

Portal（``:9002``）需统一密码登录，个人作业/配额接口未知，本模块只给入口。
bundle 路径带 hash，先取首页解析出当前 JS 地址再抓（缓存一份，页面结构
变化时抛 :class:`~westlake_survival.exceptions.ParseError`）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import requests

from westlake_survival._cache import http_get_with_etag
from westlake_survival._net import DEFAULT_TIMEOUT
from westlake_survival.discovery import direct_session
from westlake_survival.exceptions import ParseError, WestlakeError

__all__ = [
    "HPC_MAIN",
    "HPC_PORTAL",
    "AI_GATEWAY",
    "AI_KEY_URL",
    "AI_MODELS",
    "AI_TOOL_PANELS",
    "HPC_TOKEN_FILENAME",
    "TOKEN_ENV_VARS",
    "read_hpc_token",
    "save_hpc_token",
    "sync_hpc_token",
    "QueueSpec",
    "HpcOverview",
    "overview",
    "ai_service",
    "ai_gateway_probe",
    "cli_group",
]

HPC_MAIN = "https://hpc.westlake.edu.cn/"
HPC_PORTAL = "https://hpc.westlake.edu.cn:9002/login.html"

#: 令牌持久化文件名（~/.westlake_survival/hpc_token.txt）。
HPC_TOKEN_FILENAME = "hpc_token.txt"
TOKEN_ENV_VARS = ("WESTLAKE_HPC_TOKEN", "HPC_API_KEY")

#: Westlake AI——HPC 中心运营的 OpenAI 兼容大模型网关（New API，2026-10-25
#: 从主站 bundle 反出）。令牌凭校园 SSO 在 key_url 免费自助领取；网关
#: ``/v1/models`` 未带令牌返回 401（new_api_error）。
AI_GATEWAY = "https://hpc-api.westlake.edu.cn/v1"
AI_KEY_URL = "https://hpc.westlake.edu.cn/newapi-auto-key"
#: bundle 配置模板里的模型清单（页面标题「Westlake AI 私有令牌申请」）。
AI_MODELS = ("GLM-5.3-Flash", "DeepSeek-V4.1-Flash", "Qwen 3.8")
#: 官网 AI Campus 为这些客户端生成现成配置模板（opencode 模板含完整 provider JSON）。
AI_TOOL_PANELS = ("opencode", "claude", "vscode", "deepseek")

#: 队列表在 bundle 里的锚点。
_QUEUE_ANCHOR = "Number of Nodes"

#: 集群名（手册路由里的三个 showPart 值）。
_CLUSTERS = ("科学工程计算集群", "人工智能集群", "Cryo-EM")


class QueueSpec:
    """一个队列的配置（同队列多行配置合成一组）。"""

    def __init__(self, name: str, nodes: str, specs: list[tuple[str, str]]):
        self.name = name
        self.nodes = nodes
        self.specs = specs  # [(CPU, ...), (Memory, ...), (NVME, ...)]


class HpcOverview:
    """主站解析结果。"""

    def __init__(self, queues: list[QueueSpec], clusters: list[str]):
        self.queues = queues
        self.clusters = clusters


def _fetch_bundle(session: requests.Session, timeout: float) -> str:
    """取首页并解析出当前 app bundle 的完整 URL 与内容（强制 UTF-8）。"""
    response = session.get(HPC_MAIN, timeout=timeout, verify=False)
    html = response.content.decode("utf-8", errors="replace")
    match = re.search(r'src="(?:/)?(js/app\.[0-9a-f]+\.js)"', html)
    if not match:
        raise ParseError("HPC 首页未找到 app bundle 引用（结构可能已变化）")
    bundle_url = HPC_MAIN + match.group(1)
    # bundle 是无 charset 的 JS：不走通用缓存解码，强制 UTF-8 后自管缓存。
    from westlake_survival import _cache

    cache_name = "hpc/app_bundle_utf8.js"
    cached = _cache.load_json(cache_name, default=None) or {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}
    bundle_response = session.get(bundle_url, headers=headers, timeout=timeout, verify=False)
    if bundle_response.status_code == 304 and cached.get("body"):
        return str(cached["body"])
    bundle_response.raise_for_status()
    text = bundle_response.content.decode("utf-8", errors="replace")
    etag = bundle_response.headers.get("ETag")
    if etag:
        _cache.save_json(cache_name, {"etag": etag, "body": text})
    return text


def _parse_queues(bundle: str) -> list[QueueSpec]:
    """从渲染函数字符串里还原队列表。

    形态：``[e._v("<cell>")]`` 顺序即单元格顺序；每队列是
    ``rowspan`` 行（队列名、节点数）后跟多组 (键, 值) 行。
    """
    start = bundle.find(_QUEUE_ANCHOR)
    if start == -1:
        raise ParseError("bundle 中未找到队列表锚点")
    window = bundle[start : start + 20000]
    cells = re.findall(r'e\._v\("([^"]{1,60})"\)', window)
    queues: list[QueueSpec] = []
    i = 0
    # 单元格序列：[表头键…] 队列名, 节点数, (键, 值)×N, …循环
    while i + 1 < len(cells):
        name, nodes = cells[i], cells[i + 1]
        # 队列名非空且下一格是纯数字节点数；表头键（Queue 等）不匹配该模式
        if not name.strip() or not re.fullmatch(r"\d+", nodes.strip()):
            i += 1
            continue
        specs: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        j = i + 2
        # 站点部分集群用中文键（内存/显存/硬盘），旧键集会让这些行静默丢失。
        # 同一条队列内键不会重复；键重复说明已经走到下一条队列——而那条队列的名字
        # 恰好可能就叫 CPU/GPU，不做这个判断会被当成上一个队列的键吞掉（实测 17/18）。
        while (
            j + 1 < len(cells)
            and cells[j] in ("CPU", "Memory", "内存", "NVME", "GPU", "显存", "硬盘", "Other")
            and cells[j] not in seen_keys
        ):
            seen_keys.add(cells[j])
            specs.append((cells[j], cells[j + 1]))
            j += 2
        if specs:
            queues.append(QueueSpec(name=name.strip(), nodes=nodes.strip(), specs=specs))
            i = j
        else:
            i += 1
    if len(queues) < 3:
        raise ParseError(f"队列表解析异常（仅 {len(queues)} 条，结构可能已变化）")
    return queues


def overview(
    *,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> HpcOverview:
    """解析 HPC 主站：队列配置表 + 集群名单。

    Raises:
        WestlakeError: 网络失败。
        ParseError: bundle 结构变化导致解析失败。
    """
    session = session if session is not None else direct_session()
    effective = timeout if timeout is not None else DEFAULT_TIMEOUT
    try:
        bundle = _fetch_bundle(session, effective)
    except requests.Timeout as exc:
        raise WestlakeError("HPC 主站请求超时") from exc
    except requests.RequestException as exc:
        raise WestlakeError(f"HPC 主站请求失败：{exc}") from exc
    clusters = [c for c in _CLUSTERS if c in bundle]
    return HpcOverview(queues=_parse_queues(bundle), clusters=clusters)


def _token_path() -> Path:
    override = os.environ.get("WESTLAKE_HOME")
    root = Path(override) if override else Path.home() / ".westlake_survival"
    return root / HPC_TOKEN_FILENAME


def read_hpc_token() -> str | None:
    """读取已配置的集群 API Key（环境变量优先，其次 ~/.westlake_survival/hpc_token.txt）。"""
    for env in TOKEN_ENV_VARS:
        val = os.environ.get(env)
        if val and val.strip():
            return val.strip()
    path = _token_path()
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            if lines and lines[0].strip():
                return lines[0].strip()
        except OSError:
            pass
    return None


def save_hpc_token(token: str) -> Path:
    """保存集群 API Key 到配置文件（0600 权限）。"""
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def sync_hpc_token(sid: str | None = None, password: str | None = None) -> tuple[str, dict]:
    """通过统一认证与 NewAPI 自动申请页面获取或读取集群私有令牌。

    流程：
    1. 读统一凭据（学号 + 密码）；
    2. 对接 ecs.westlake.edu.cn:30300/auth/start 触发 IAM OAuth2 认证；
    3. 跟随回调建立 newapi-auto-key 会话并提取分配的 sk- 令牌；
    4. 自动落盘至 ~/.westlake_survival/hpc_token.txt。
    """
    import json
    import urllib.parse
    from westlake_survival import iam
    from westlake_survival.sso import read_credentials

    if not sid or not password:
        sid, password = read_credentials()

    session = direct_session()
    start_url = (
        "https://ecs.westlake.edu.cn:30300/auth/start?"
        "redirect_uri=https%3A%2F%2Fhpc.westlake.edu.cn%2Fnewapi-auto-key%2Fauth%2Fcallback%3Flang%3Dzh"
        "&state=sync-token"
    )
    session, location = iam.authenticate(start_url, sid, password, session=session)
    response = session.get(location, verify=False, allow_redirects=True)
    demo_session = session.cookies.get("westlake_demo_session")

    key = ""
    token_details: dict = {}
    if demo_session:
        try:
            payload = json.loads(urllib.parse.unquote(demo_session))
            token_details = payload.get("newApiToken") or {}
            key = str(token_details.get("key") or "").strip()
        except Exception:
            pass

    if not key:
        match = re.search(r"sk-[a-zA-Z0-9_-]{20,}", response.text)
        if match:
            key = match.group(0)
            token_details = {"key": key, "message": "已从页面响应提取"}

    if not key:
        raise WestlakeError("未能从集群 NewAPI 认证会话中提取到有效的 API Key。")

    save_hpc_token(key)
    return key, token_details


# --------------------------------------------------------------------------- #
# Westlake AI（OpenAI 兼容大模型网关）
# --------------------------------------------------------------------------- #
def ai_service(*, session: requests.Session | None = None, timeout: float | None = None) -> dict:
    """Westlake AI 网关服务信息：网关地址 / 领令牌入口 / 模型清单。

    数据从主站 bundle 反出（静态清单）；``probe=True`` 语义由调用方用
    :func:`ai_gateway_probe` 实测网关可达性。
    """
    return {
        "gateway": AI_GATEWAY,
        "key_url": AI_KEY_URL,
        "models": list(AI_MODELS),
        "tool_panels": list(AI_TOOL_PANELS),
        "usage": (
            "OpenAI 兼容：POST {gateway}/chat/completions，"
            "Authorization: Bearer <私有令牌>；令牌在 key_url 用校园 SSO 免费领取"
        ).format(gateway=AI_GATEWAY),
    }


def ai_gateway_probe(
    *, session: requests.Session | None = None, token: str | None = None, timeout: float = 8.0
) -> dict:
    """探测网关存活：带令牌测试 /models 返回 200，无令牌 401=在役。"""
    session = session if session is not None else direct_session()
    key = token or read_hpc_token()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = session.get(f"{AI_GATEWAY}/models", headers=headers, timeout=timeout)
        if resp.status_code == 200:
            try:
                models = [m["id"] for m in resp.json().get("data", [])]
            except Exception:
                models = []
            return {
                "alive": True,
                "status": 200,
                "authenticated": True,
                "models": models,
                "note": f"在役且认证成功（可用模型：{'、'.join(models)}）" if models else "在役且认证成功",
            }
        body = resp.text[:160]
        return {
            "alive": resp.status_code in (401, 403),
            "status": resp.status_code,
            "authenticated": False,
            "models": [],
            "note": "网关在役（需令牌）" if resp.status_code in (401, 403) else body,
        }
    except requests.RequestException as exc:
        return {"alive": False, "status": 0, "authenticated": False, "models": [], "note": f"{exc.__class__.__name__}: {exc}"[:120]}


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

    @click.group(name="hpc", help="高性能计算中心：队列配置（公开）与入口。")
    def group() -> None:
        """``westlake hpc overview``。"""

    @group.command(name="overview")
    @handle
    def overview_cmd() -> None:
        """集群队列与节点配置表（来自主站公开数据）。"""
        data = overview()
        click.echo(f"集群：{'、'.join(data.clusters) or '—'}")
        click.echo(f"队列：{len(data.queues)} 个")
        for q in data.queues:
            click.echo(f"  {q.name}（{q.nodes} 节点）")
            for key, value in q.specs:
                click.echo(f"     {key:<8} {value}")
        click.echo(f"\nPortal（统一密码登录）：{HPC_PORTAL}")

    @group.command(name="ai")
    @handle
    def ai_cmd() -> None:
        """Westlake AI：OpenAI 兼容大模型网关（网关/领令牌/模型清单/配置状态）。"""
        info = ai_service()
        token = read_hpc_token()
        probe = ai_gateway_probe(token=token)
        token_str = (token[:7] + "..." + token[-4:]) if (token and len(token) > 12) else ("已配置" if token else "未配置")

        click.echo(f"网关端点：{info['gateway']}（{'在役' if probe['alive'] else probe['note']}）")
        click.echo(f"私有令牌：{token_str}（领令牌入口：{info['key_url']}）")
        if probe.get("authenticated") and probe.get("models"):
            click.echo(f"可用模型：{'、'.join(probe['models'])}")
        else:
            click.echo(f"宣称模型：{'、'.join(info['models'])}")
        click.echo(f"客户端模板：{'、'.join(info['tool_panels'])}（官网 AI Campus 页生成）")
        if not token:
            click.echo("\n提示：运行 `westlake hpc sync-key` 即可基于统一身份认证自动领取/配置令牌。")
        else:
            click.echo("\n--- 快速使用示例 (OpenAI API 兼容) ---")
            click.echo(f"curl {AI_GATEWAY}/chat/completions \\")
            click.echo(f"  -H 'Authorization: Bearer {token}' \\")
            click.echo("  -H 'Content-Type: application/json' \\")
            click.echo('  -d \'{"model":"deepseek-flash","messages":[{"role":"user","content":"你好"}]}\'')

    @group.command(name="sync-key")
    @handle
    def sync_key_cmd() -> None:
        """通过统一认证自动获取并配置 Westlake AI 私有令牌。"""
        token, details = sync_hpc_token()
        masked = token[:7] + "..." + token[-4:] if len(token) > 12 else "已配置"
        click.secho(f"✔ 成功获取并配置集群 API 令牌：{masked}", fg="green", bold=True)
        click.echo("  存储文件：~/.westlake_survival/hpc_token.txt")
        click.echo(f"  网关端点：{AI_GATEWAY}")
        probe = ai_gateway_probe(token=token)
        if probe.get("authenticated") and probe.get("models"):
            click.echo(f"  可用模型：{'、'.join(probe['models'])}")

    @group.command(name="set-key")
    @click.argument("key")
    @handle
    def set_key_cmd(key: str) -> None:
        """手动保存集群 API 令牌。"""
        save_hpc_token(key)
        masked = key[:7] + "..." + key[-4:] if len(key) > 12 else "已配置"
        click.secho(f"✔ 集群 API 令牌已保存：{masked}", fg="green")
        click.echo("  存储文件：~/.westlake_survival/hpc_token.txt")

    return group


cli_group = _cli()
