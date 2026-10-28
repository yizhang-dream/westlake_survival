"""联创自助文印（PMS）数据模型。

约定与 :mod:`westlake_survival.canvas.models` 一致：

- 每个模型都是 :func:`dataclasses.dataclass`，字段顺序贴近服务端返回的
  **原始字段名**（``dwXxx`` / ``szXxx``），另加若干只读 ``property``
  把位图/枚举翻译成人类可读值。原始字段名写在每个字段的注释里，方便对照
  ``api_notes.md``。
- 每个模型都提供 ``from_json`` 类方法，**容忍缺字段、None、脏类型**：
  缺失字段落默认值，绝不抛 ``KeyError``。
- 所有时间字段统一还原为 ``Asia/Shanghai`` 时区的 aware ``datetime``。
  服务端用「日期整数 + 时间整数」两个字段拼一个时刻：
  ``dwCreateDate=20260922``、``dwCreateTime=100000`` 表示 2026-09-22
  10:00:00（时间整数是 ``HHMMSS`` 打包，见前端 ``fommateTimeToHHMM``）。

模型只做转换，不发请求；请求逻辑见
:mod:`westlake_survival.pms.client`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# --------------------------------------------------------------------------
# 时区与基础转换工具
# --------------------------------------------------------------------------


def _load_china_tz():
    """加载 ``Asia/Shanghai``；无 IANA 数据库时退回 ``dateutil`` / 固定 +08:00。"""
    try:
        return ZoneInfo("Asia/Shanghai")
    except ZoneInfoNotFoundError:  # pragma: no cover - 依赖系统 tzdata
        try:
            from dateutil import tz as _dateutil_tz

            zone = _dateutil_tz.gettz("Asia/Shanghai")
            if zone is not None:
                return zone
        except Exception:  # pragma: no cover - 防御性
            pass
        return timezone(timedelta(hours=8))


#: 全库统一的中国时区。
CHINA_TZ = _load_china_tz()


def _as_dict(data: Any) -> Mapping[str, Any]:
    """把 API 返回项规整为 Mapping；非 Mapping 时返回空字典。"""
    return data if isinstance(data, Mapping) else {}


def _as_int(value: Any) -> int | None:
    """尽力转 int；``None``/空串/非法值一律返回 ``None``。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def _as_str(value: Any) -> str | None:
    """把值规整为字符串；``None``/空串返回 ``None``。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_packed_datetime(date_value: Any, time_value: Any) -> datetime | None:
    """把「日期整数 + 时间整数」还原为 ``CHINA_TZ`` 的 aware datetime。

    ``date_value`` 形如 ``20260922``（``YYYYMMDD``），``time_value`` 形如
    ``100000``（``HHMMSS``，位数不足左侧补 0）。任一缺失或非法 → ``None``。
    """
    date_int = _as_int(date_value)
    time_int = _as_int(time_value)
    if date_int is None or date_int <= 0:
        return None
    text = str(date_int).zfill(8)
    try:
        year, month, day = int(text[0:4]), int(text[4:6]), int(text[6:8])
    except ValueError:
        return None
    hour = minute = second = 0
    if time_int is not None and time_int >= 0:
        ttext = str(time_int).zfill(6)[-6:]
        try:
            hour, minute, second = (
                int(ttext[0:2]),
                int(ttext[2:4]),
                int(ttext[4:6]),
            )
        except ValueError:
            hour = minute = second = 0
    try:
        naive = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    return naive.replace(tzinfo=CHINA_TZ)


def parse_epoch(value: Any) -> datetime | None:
    """把 Unix 秒（如 ``dwUpdateTime``）还原为 ``CHINA_TZ`` aware datetime。"""
    seconds = _as_int(value)
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(CHINA_TZ)
    except (OverflowError, OSError, ValueError):  # pragma: no cover - 越界脏数据
        return None


def cents_to_yuan(value: Any) -> float | None:
    """把服务端的「分」转为「元」（服务端金额字段单位统一为分）。"""
    amount = _as_int(value)
    if amount is None:
        return None
    return amount / 100.0


# --------------------------------------------------------------------------
# 位图 / 枚举
# --------------------------------------------------------------------------

#: ``Station.dwProperty`` 位图：可用功能。
STATION_FUNC_PRINT = 0x01
STATION_FUNC_COPY = 0x02
STATION_FUNC_SCAN = 0x04
STATION_FUNC_COLOR = 0x08

#: ``dwPaperID`` 取值与纸型名的映射（实测 A3=8, A4=9；其余按服务端名为准）。
PAPER_ID_NAMES = {8: "A3", 9: "A4"}

#: 网点名里的校区前缀与颜色后缀（实测 ``szCampus``/``szRoomName``/
#: ``szPosition`` 均为空串，校区/位置信息只编码在 ``szName`` 里，
#: 形如「云栖图书馆彩色」→ 校区「云栖」、位置「图书馆」）。
_CAMPUS_PREFIXES = ("云栖", "云谷")
_COLOR_SUFFIXES = ("彩色", "黑白")

#: ``dwStatus`` 位图：设备状态。
STATION_STATUS_DISABLED = 0
STATION_STATUS_IDLE = 0x01
STATION_STATUS_BUSY = 0x02
STATION_STATUS_UNAVAILABLE_MASK = 0x20 | 0x200 | 0x400 | 0x800 | 0x1000 | 0x2000 | 0x10000


def paper_name(paper_id: Any) -> str | None:
    """把 ``dwPaperID`` 翻译为纸型名（未知值返回原始数字的字符串）。"""
    value = _as_int(paper_id)
    if value is None:
        return None
    if value in PAPER_ID_NAMES:
        return PAPER_ID_NAMES[value]
    if value <= 0:
        return None
    return str(value)


# --------------------------------------------------------------------------
# 模型
# --------------------------------------------------------------------------


@dataclass
class Paper:
    """纸型（``GET /api/client/Paper/GetPaper`` 的 ``result`` 元素）。"""

    id: int | None = None  # dwPaperID
    name: str | None = None  # szPaperName
    width_mm: float | None = None  # dwWidth（单位 0.01mm）
    height_mm: float | None = None  # dwHeight（单位 0.01mm）
    status: int | None = None  # dwStatus
    tray_index: int | None = None  # dwTrayIndex

    @classmethod
    def from_json(cls, data: Any) -> "Paper":
        obj = _as_dict(data)
        width = _as_int(obj.get("dwWidth"))
        height = _as_int(obj.get("dwHeight"))
        return cls(
            id=_as_int(obj.get("dwPaperID")),
            name=_as_str(obj.get("szPaperName")),
            width_mm=width / 100.0 if width is not None else None,
            height_mm=height / 100.0 if height is not None else None,
            status=_as_int(obj.get("dwStatus")),
            tray_index=_as_int(obj.get("dwTrayIndex")),
        )


@dataclass
class Station:
    """打印/复印/扫描网点（``GET /api/client/Station/GetList`` 的 ``result`` 元素）。"""

    dev_sn: int | None = None  # dwDevSN
    name: str | None = None  # szName
    ip: str | None = None  # szIP
    position: str | None = None  # szPosition
    status: int | None = None  # dwStatus（位图）
    status_text: str | None = None  # szStatInfo
    model: int | None = None  # dwModel
    function: int | None = None  # dwFunction
    ctrl_type: int | None = None  # dwCtrlType
    capabilities: int | None = None  # dwProperty（位图，见 STATION_FUNC_*）
    campus: str | None = None  # szCampus
    room_name: str | None = None  # szRoomName
    dept_name: str | None = None  # szDeptName
    printer_driver: str | None = None  # szPrtDriver
    tel: str | None = None  # szTel
    mac: str | None = None  # szMAC
    card_ip: str | None = None  # szCardIP
    trays: list[int] = field(default_factory=list)  # dwTrayPaper1..4（非 0 项）
    open_time: int | None = None  # dwOpenTime（当日分钟数）
    close_time: int | None = None  # dwCloseTime（当日分钟数）
    changed_at: datetime | None = None  # dwChgTime（Unix 秒）
    updated_at: datetime | None = None  # dwUpdateTime（Unix 秒）
    memo: str | None = None  # szMemo
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> "Station":
        obj = _as_dict(data)
        trays: list[int] = []
        for key in ("dwTrayPaper1", "dwTrayPaper2", "dwTrayPaper3", "dwTrayPaper4"):
            value = _as_int(obj.get(key))
            if value:
                trays.append(value)
        return cls(
            dev_sn=_as_int(obj.get("dwDevSN")),
            name=_as_str(obj.get("szName")),
            ip=_as_str(obj.get("szIP")),
            position=_as_str(obj.get("szPosition")),
            status=_as_int(obj.get("dwStatus")),
            status_text=_as_str(obj.get("szStatInfo")),
            model=_as_int(obj.get("dwModel")),
            function=_as_int(obj.get("dwFunction")),
            ctrl_type=_as_int(obj.get("dwCtrlType")),
            capabilities=_as_int(obj.get("dwProperty")),
            campus=_as_str(obj.get("szCampus")),
            room_name=_as_str(obj.get("szRoomName")),
            dept_name=_as_str(obj.get("szDeptName")),
            printer_driver=_as_str(obj.get("szPrtDriver")),
            tel=_as_str(obj.get("szTel")),
            mac=_as_str(obj.get("szMAC")),
            card_ip=_as_str(obj.get("szCardIP")),
            trays=trays,
            open_time=_as_int(obj.get("dwOpenTime")),
            close_time=_as_int(obj.get("dwCloseTime")),
            changed_at=parse_epoch(obj.get("dwChgTime")),
            updated_at=parse_epoch(obj.get("dwUpdateTime")),
            memo=_as_str(obj.get("szMemo")),
            raw=dict(obj),
        )

    @property
    def campus_display(self) -> str | None:
        """校区：``szCampus`` 非空直接用；否则从网点名前缀（云栖/云谷）提取。"""
        if self.campus:
            return self.campus
        name = self.name or ""
        for prefix in _CAMPUS_PREFIXES:
            if name.startswith(prefix):
                return prefix
        return None

    @property
    def position_display(self) -> str | None:
        """位置：``szPosition``/``szRoomName`` 非空直接用；否则从网点名剥掉
        校区前缀与颜色后缀得到（「云栖图书馆彩色」→「图书馆」）。
        网点名不含已知校区前缀时返回 ``None``（不拿全名冒充位置）。
        """
        if self.position or self.room_name:
            return self.position or self.room_name
        name = self.name or ""
        for prefix in _CAMPUS_PREFIXES:
            if name.startswith(prefix):
                rest = name[len(prefix) :]
                for suffix in _COLOR_SUFFIXES:
                    if rest.endswith(suffix):
                        rest = rest[: -len(suffix)]
                return rest or None
        return None

    @property
    def papers(self) -> list[str]:
        """该网点纸盒支持的纸型名（去重后按 A3/A4 顺序）。"""
        names = [name for name in (paper_name(tray) for tray in self.trays) if name]
        ordered = [name for name in ("A3", "A4") if name in names]
        ordered.extend(name for name in names if name not in ordered)
        return ordered

    @property
    def is_idle(self) -> bool:
        """``dwStatus`` 为「空闲」位（0x01）时为真。"""
        return bool(self.status and self.status & STATION_STATUS_IDLE)

    @property
    def is_busy(self) -> bool:
        """``dwStatus`` 为「忙碌」位（0x02）时为真。"""
        return bool(self.status and self.status & STATION_STATUS_BUSY)

    @property
    def is_disabled(self) -> bool:
        """``dwStatus == 0`` 表示设备未开放。"""
        return self.status == STATION_STATUS_DISABLED

    @property
    def supports_print(self) -> bool:
        return bool(self.capabilities and self.capabilities & STATION_FUNC_PRINT)

    @property
    def supports_copy(self) -> bool:
        return bool(self.capabilities and self.capabilities & STATION_FUNC_COPY)

    @property
    def supports_scan(self) -> bool:
        return bool(self.capabilities and self.capabilities & STATION_FUNC_SCAN)

    @property
    def supports_color(self) -> bool:
        return bool(self.capabilities and self.capabilities & STATION_FUNC_COLOR)


@dataclass
class PrintJob:
    """打印任务（``GET /api/client/PrintJob/Get`` 的 ``result`` 元素）。

    ``paper_detail`` 由服务端的 ``szPaperDetail`` 字符串字段反序列化而来
    （该字段本身是一段 JSON，形如
    ``[{"dwPaperID":9,"dwBWPages":2,"dwColorPages":0}, ...]``）。
    """

    id: int | None = None  # dwJobId
    name: str | None = None  # szJobName
    status: int | None = None  # dwStatus
    status_text: str | None = None  # szStatus
    copies: int | None = None  # dwCopies
    attribute: str | None = None  # szAttribe（含 single/vdup/color 关键字）
    dev_sn: int | None = None  # dwDevSN
    created_date: int | None = None  # dwCreateDate
    created_time: int | None = None  # dwCreateTime
    printed_page: int | None = None  # dwPrintedPage
    pages: int | None = None  # dwPages
    paper_detail: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> "PrintJob":
        obj = _as_dict(data)
        return cls(
            id=_as_int(obj.get("dwJobId")),
            name=_as_str(obj.get("szJobName")),
            status=_as_int(obj.get("dwStatus")),
            status_text=_as_str(obj.get("szStatus")),
            copies=_as_int(obj.get("dwCopies")),
            attribute=_as_str(obj.get("szAttribe")),
            dev_sn=_as_int(obj.get("dwDevSN")),
            created_date=_as_int(obj.get("dwCreateDate")),
            created_time=_as_int(obj.get("dwCreateTime")),
            printed_page=_as_int(obj.get("dwPrintedPage")),
            pages=_as_int(obj.get("dwPages")),
            paper_detail=parse_paper_detail(obj.get("szPaperDetail")),
            raw=dict(obj),
        )

    @property
    def created_at(self) -> datetime | None:
        """``dwCreateDate`` + ``dwCreateTime`` 拼出的提交时刻。"""
        return parse_packed_datetime(self.created_date, self.created_time)

    @property
    def filename(self) -> str | None:
        """``name`` 的别名（服务端字段是 ``szJobName``）。"""
        return self.name

    @property
    def duplex(self) -> str | None:
        """单双面：``single``（单面）/ ``vdup``（双面长边）/ ``vdup_short``（双面短边）。

        ``szAttribe`` 为空（或无该字段）时返回 ``None``；非空但无法归类
        （既非 single 也非 vdup/vdup_short，例如含糊的 ``duplex`` 或只有
        ``color``）返回中性的 ``"unknown"``，不再兜底误判为某一具体模式。

        判序要点：``vdup_short`` 必须先于 ``vdup`` 判断，因为
        ``"vdup_short"`` 本身包含子串 ``"vdup"``，先判 ``vdup`` 会把短边
        双面误分类成长边双面。
        """
        text = (self.attribute or "").lower()
        if not text:
            return None
        if "single" in text:
            return "single"
        if "vdup_short" in text:
            return "vdup_short"
        if "vdup" in text:
            return "vdup"
        return "unknown"

    @property
    def is_color(self) -> bool:
        """``szAttribe`` 含 ``color`` 即为彩色。"""
        return "color" in (self.attribute or "").lower()

    @property
    def color(self) -> bool:
        """``is_color`` 的别名。"""
        return self.is_color

    @property
    def total_pages(self) -> int:
        """各纸型 ``dwBWPages + dwColorPages`` 之和。"""
        total = 0
        for item in self.paper_detail:
            total += _as_int(item.get("dwBWPages")) or 0
            total += _as_int(item.get("dwColorPages")) or 0
        return total


@dataclass
class ScanJob:
    """扫描任务（``GET /api/client/Scan/Get`` 的 ``result`` 元素）。"""

    id: int | None = None  # dwJobId
    display_name: str | None = None  # szDisplayName
    file_name: str | None = None  # szFileName
    file_size: int | None = None  # dwFileSize（字节）
    status: int | None = None  # dwStatus（位图）
    submit_date: int | None = None  # dwSubmitDate
    submit_time: int | None = None  # dwSubmitTime
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> "ScanJob":
        obj = _as_dict(data)
        return cls(
            id=_as_int(obj.get("dwJobId")),
            display_name=_as_str(obj.get("szDisplayName")),
            file_name=_as_str(obj.get("szFileName")) or _as_str(obj.get("szDisplayName")),
            file_size=_as_int(obj.get("dwFileSize")),
            status=_as_int(obj.get("dwStatus")),
            submit_date=_as_int(obj.get("dwSubmitDate")),
            submit_time=_as_int(obj.get("dwSubmitTime")),
            raw=dict(obj),
        )

    @property
    def submitted_at(self) -> datetime | None:
        """``dwSubmitDate`` + ``dwSubmitTime`` 拼出的提交时刻。"""
        return parse_packed_datetime(self.submit_date, self.submit_time)


@dataclass
class UsageRecord:
    """一条消费/用量明细（``POST /api/client/Report/DetailPage`` 的 ``result`` 元素）。

    服务端金额字段单位是「分」，``cost`` 等属性已换算为「元」。
    """

    date: int | None = None  # dwDate
    time: int | None = None  # dwTime
    type: int | None = None  # dwType（1 打印 / 2 复印 / 3 扫描，实测口径）
    pages: int | None = None  # dwPages
    copies: int | None = None  # dwCopies
    paper_id: int | None = None  # dwPaperID
    card_money: int | None = None  # dwUsedCardMoney（分）
    free_money: int | None = None  # dwUsedFreeMoney（分，补助）
    local_money: int | None = None  # dwUsedMoney（分，本地消费）
    settle_type: int | None = None  # dwSettleType
    job_id: int | None = None  # dwJobId
    name: str | None = None  # szJobName / szName
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> "UsageRecord":
        obj = _as_dict(data)
        return cls(
            date=_as_int(obj.get("dwDate")),
            time=_as_int(obj.get("dwTime")),
            type=_as_int(obj.get("dwType")),
            pages=_as_int(obj.get("dwPages")),
            copies=_as_int(obj.get("dwCopies")),
            paper_id=_as_int(obj.get("dwPaperID")),
            card_money=_as_int(obj.get("dwUsedCardMoney")),
            free_money=_as_int(obj.get("dwUsedFreeMoney")),
            local_money=_as_int(obj.get("dwUsedMoney")),
            settle_type=_as_int(obj.get("dwSettleType")),
            job_id=_as_int(obj.get("dwJobId")),
            name=_as_str(obj.get("szJobName")) or _as_str(obj.get("szName")),
            raw=dict(obj),
        )

    @property
    def time_at(self) -> datetime | None:
        """``dwDate`` + ``dwTime`` 拼出的发生时刻。"""
        return parse_packed_datetime(self.date, self.time)

    @property
    def cost(self) -> float:
        """本次消费合计（元）= 卡消费 + 补助 + 本地消费。"""
        cents = (self.card_money or 0) + (self.free_money or 0) + (self.local_money or 0)
        return cents / 100.0

    @property
    def cost_yuan(self) -> float:
        """``cost`` 的别名，便于阅读。"""
        return self.cost

    @property
    def paper(self) -> str | None:
        """纸型名。"""
        return paper_name(self.paper_id)


@dataclass
class UsageSummary:
    """按类型汇总的用量（``POST /api/client/Report/Stat`` 的 ``result`` 元素）。"""

    type: int | None = None  # dwType
    times: int | None = None  # dwUseTimes
    pages: int | None = None  # dwPages
    card_money: int | None = None  # dwUsedCardMoney（分）
    free_money: int | None = None  # dwUsedFreeMoney（分）
    local_money: int | None = None  # dwUsedMoney（分）
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> "UsageSummary":
        obj = _as_dict(data)
        return cls(
            type=_as_int(obj.get("dwType")),
            times=_as_int(obj.get("dwUseTimes")),
            pages=_as_int(obj.get("dwPages")),
            card_money=_as_int(obj.get("dwUsedCardMoney")),
            free_money=_as_int(obj.get("dwUsedFreeMoney")),
            local_money=_as_int(obj.get("dwUsedMoney")),
            raw=dict(obj),
        )

    @property
    def cost(self) -> float:
        """合计消费（元）。"""
        cents = (self.card_money or 0) + (self.free_money or 0) + (self.local_money or 0)
        return cents / 100.0


@dataclass
class UsagePage:
    """一页用量明细（``DetailPageResponse``）。"""

    records: list[UsageRecord] = field(default_factory=list)
    total_page: int | None = None  # dwTotalPage
    total_count: int | None = None  # dwTotalCount / dwTotalRows（若返回）
    raw: dict[str, Any] = field(default_factory=dict)


def parse_paper_detail(value: Any) -> list[dict[str, Any]]:
    """把 ``szPaperDetail``（JSON 字符串或已是列表）规整为 ``list[dict]``。

    容忍：``None``、空串、非法 JSON、元素不是 dict —— 一律跳过。
    """
    if value is None:
        return []
    payload = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return []
    if isinstance(payload, Mapping):
        payload = [payload]
    if not isinstance(payload, (list, tuple)):
        return []
    return [dict(item) for item in payload if isinstance(item, Mapping)]


__all__ = [
    "CHINA_TZ",
    "PAPER_ID_NAMES",
    "STATION_FUNC_COLOR",
    "STATION_FUNC_COPY",
    "STATION_FUNC_PRINT",
    "STATION_FUNC_SCAN",
    "STATION_STATUS_BUSY",
    "STATION_STATUS_DISABLED",
    "STATION_STATUS_IDLE",
    "Paper",
    "PrintJob",
    "ScanJob",
    "Station",
    "UsagePage",
    "UsageRecord",
    "UsageSummary",
    "cents_to_yuan",
    "paper_name",
    "parse_epoch",
    "parse_packed_datetime",
    "parse_paper_detail",
]
