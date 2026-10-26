"""按「功能词」而非主机名扫活子域的临时侦查脚本（2026-10-27）。

用途：验证 discovery 的候选词表漏掉多少真实系统。先 DNS 解析，再对解析
成功的做一次只读 GET。结果打印为 TSV，便于和 SERVICE_REGISTRY 对比。

用法：python tools/host_hunt.py [--words 额外词,逗号分隔]

局限：只扫单级名（``<词>.westlake.edu.cn``）。二级子域如 ``seats.library``
猜不到，只能靠人工登记进 ``discovery.EVIDENCE_HOSTS``。
"""

from __future__ import annotations

import socket
import sys
from concurrent.futures import ThreadPoolExecutor

# 功能词/供应商词表：按「校园里存在什么服务」组织，而不是按已知主机名。
WORDS = """
sport sports gym stadium venue venues swim swimming pool fitness court courts field
playground sportvenue seat seats studyroom studyrooms study selfstudy room rooms
classroom classrooms meeting meetings seminar seminars hall activity activities
club clubs student students stunion union youth volunteer practice social second
credit credits campus life service services card ecard ykt pay payment recharge
wallet express parcel delivery post laundry wash repair maintenance fix dorm
dormitory hostel housing hospital clinic health medical doctor appointment appt
vaccine checkup physical exam exams test cet neea ielts toefl course courses
elearning lms mooc teach teaching learning blackboard chaoxing yuketang
zhihuishu erya borrow printer copy scan cloudprint pms job jobs career careers
recruit employment donate giving fund foundation finance reimburse expense
invoice purchase tender asset assets equipment lab labs safety chem hazard bio
animal ethics irb grant project research sci paper patent tech transfer industry
partner international exchange visa global summer camp admission admissions
graduate gradschool undergrad oaa jwc jwgl jx ehall ehdc ivan home portal wechat
weixin wecom dingtalk feishu lark zoom teams video live media stream notice
notices bulletin announce staff faculty teacher eval survey questionnaire form
flow workflow bpm approval sign esign doc docs disk cloud storage backup gitlab
svn wiki jira ticket help helpdesk status monitor admin dev staging demo v2
mobile open gateway proxy cache cdn static cms trs booking2 reserve reservation
reservations yuyue yy apptbooking sportcenter sportscenter tiyu tic
""".split()

TIMEOUT = 3.0


def resolves(host: str) -> str:
    try:
        socket.gethostbyname(host)
        return host
    except OSError:
        return ""


def main() -> int:
    extra = []
    if "--words" in sys.argv:
        extra = sys.argv[sys.argv.index("--words") + 1].split(",")
    words = sorted(set(WORDS + extra))
    with ThreadPoolExecutor(max_workers=32) as pool:
        alive = [h for h in pool.map(resolves, [f"{w}.westlake.edu.cn" for w in words]) if h]

    import re

    import requests
    from westlake_survival.discovery import SERVICE_REGISTRY

    registry = {f"{k}.westlake.edu.cn" for k, _, _ in SERVICE_REGISTRY}

    def fetch(fqdn: str) -> str:
        session = requests.Session()
        session.trust_env = False
        session.headers["User-Agent"] = "Mozilla/5.0 Chrome/140"
        try:
            r = session.get(f"https://{fqdn}/", timeout=(3, 6), verify=False, allow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            return f"{fqdn}\tERR\t{type(exc).__name__}\t"
        title = ""
        import re

        m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:20000], re.S | re.I)
        if m:
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()[:60]
        return f"{fqdn}\t{r.status_code}\t{title}\t{'IN_REGISTRY' if fqdn in registry else 'NEW'}"

    print(f"words={len(words)} resolved={len(alive)}")
    with ThreadPoolExecutor(max_workers=16) as pool:
        for line in pool.map(fetch, alive):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
