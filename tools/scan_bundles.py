"""bundle 常量段扫描器：对 JS 重站收割 API/URL/配置线索（一次性工具）。

经验来源：Westlake AI 网关藏在 HPC bundle 常量段（Bt/Gt/It 短变量链）。
本脚本对每个站：首页/壳页收 script src -> 抓 JS -> 抽 URL/api 路径/
WebSocket/键名线索，输出去重清单供人工分期。
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

urllib3.disable_warnings()

SITES = [
    ("booking", "https://booking.westlake.edu.cn/yy-sys/"),
    ("visitor", "https://visitor.westlake.edu.cn/"),
    ("taskcenter", "https://one.westlake.edu.cn/taskcenter/"),
    ("my", "https://my.westlake.edu.cn/"),
    ("map", "https://map.westlake.edu.cn/"),
    ("career", "https://career.westlake.edu.cn/"),
    ("international", "https://international.westlake.edu.cn/"),
    ("astro", "https://astro.westlake.edu.cn/"),
    ("share", "https://share.westlake.edu.cn/"),
    ("pan", "https://pan.westlake.edu.cn/"),
    ("heqdata", "https://heqdata.westlake.edu.cn/"),
    ("chatbot", "https://chatbot.westlake.edu.cn/"),
    ("hpc-portal", "https://hpc.westlake.edu.cn:9002/login.html"),
    ("imputationserver", "https://imputationserver.westlake.edu.cn/"),
    ("car", "https://car.westlake.edu.cn/"),
    ("remotework", "https://remotework.westlake.edu.cn/portal/"),
    ("exchange", "https://exchange.westlake.edu.cn/"),
    ("qiushi", "https://qiushi.westlake.edu.cn/"),
]

UA = {"User-Agent": "Mozilla/5.0"}
URL_RE = re.compile(r"https?://[A-Za-z0-9\.\-_:%/]+|/(?:api|apis|svc|service|graphql|v\d)/[A-Za-z0-9\.\-_/%{}\[\]]{2,60}")
WS_RE = re.compile(r"wss?://[^\s\"'`]{5,80}")
APIKEY_RE = re.compile(r"(api[_-]?key|apikey|token|secret|authorization)[\"']?\s*[:=]\s*[\"'][^\"']{6,60}[\"']", re.I)


def scan(host: str, root: str) -> dict:
    s = requests.Session()
    s.verify = False
    s.trust_env = False
    s.headers.update(UA)
    out = {"host": host, "scripts": 0, "urls": set(), "ws": set(), "keys": set(), "err": ""}
    try:
        r = s.get(root, timeout=10)
        html = r.text
        srcs = re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', html)
        srcs += re.findall(r'"(/_next/static/[^"]+\.js)"', html)
        seen: set[str] = set()
        for src in srcs[:25]:
            url = src if src.startswith("http") else root.rstrip("/") + "/" + src.lstrip("./")
            if url in seen:
                continue
            seen.add(url)
            try:
                js = s.get(url, timeout=10).text
            except Exception:
                continue
            out["scripts"] += 1
            out["urls"] |= {u for u in URL_RE.findall(js) if len(u) > 7}
            out["ws"] |= set(WS_RE.findall(js))
            out["keys"] |= {m[:70] for m in APIKEY_RE.findall(js)}
    except Exception as exc:
        out["err"] = f"{exc.__class__.__name__}: {exc}"[:80]
    return out


def interesting(url: str) -> bool:
    noise = (".css", ".svg", ".woff", ".ttf", "w3.org", "schema", "github.com",
             "npmjs", "unpkg", "jsdelivr", "example", "localhost", "127.0.0.1",
             "baidu.com/static", ".png", ".jpg", "fonts.gstatic", "registry")
    return not any(n in url for n in noise)


def main() -> None:
    with ThreadPoolExecutor(max_workers=6) as pool:
        for res in pool.map(lambda t: scan(*t), SITES):
            print(f"\n===== {res['host']}（{res['scripts']} 个 JS）{res['err']}")
            urls = sorted(u for u in res["urls"] if interesting(u))
            for u in urls[:22]:
                print("  ", u[:110])
            for w in sorted(res["ws"])[:4]:
                print("  WS:", w[:100])
            for k in sorted(res["keys"])[:4]:
                print("  KEY:", k[:90])


if __name__ == "__main__":
    sys.exit(main())
