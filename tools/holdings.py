"""持仓存储 + 录入工具（P1：垂类 agent 的地基 —— agent"持有并负责"的资产对象）。

═══════════════════════════════════════════════════════════════════════
为什么是地基：有了结构化持仓，agent 才从"每次让你重贴持仓的问答 bot"，
变成"记得你资产、能盯风险、能复盘"的助理。P2 看板 / P3 风险诊断都读这里。
═══════════════════════════════════════════════════════════════════════

存储：portfolio/holdings.json（已 gitignore，纯本地、不外传、不写日志）。
注意：本文件只管"存取持仓"，组合的收益/波动计算在 tools/portfolio.py，两者分开。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from claude_agent_sdk import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
    _WRITE = ToolAnnotations(readOnlyHint=False)
    _DEL = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
except Exception:  # pragma: no cover
    _RO = _WRITE = _DEL = None

PORTFOLIO_DIR = Path(__file__).resolve().parent.parent / "portfolio"
HOLDINGS_FILE = PORTFOLIO_DIR / "holdings.json"

# 大类取值（对齐吕晓彤三脚架 + 风险诊断需求）
ASSET_CLASSES = [
    "股票/股票基金", "债券/债基", "现金/货基", "商品(黄金等)", "海外", "房产", "其他",
]
# 可更新的字段（update_holding 用）
EDITABLE_FIELDS = ["name", "code", "asset_class", "sector", "amount", "cost", "currency", "note"]


# ── 持久化 ────────────────────────────────────────────────────────────
def _load() -> list[dict]:
    if not HOLDINGS_FILE.exists():
        return []
    try:
        data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    HOLDINGS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_id(items: list[dict]) -> int:
    return max((int(h.get("id", 0)) for h in items), default=0) + 1


def _find(items: list[dict], identifier: str):
    """按 id（数字）或名称（精确/包含）定位一笔持仓，返回索引或 None。"""
    ident = str(identifier).strip()
    if ident.isdigit():
        for i, h in enumerate(items):
            if int(h.get("id", 0)) == int(ident):
                return i
    for i, h in enumerate(items):
        if h.get("name") == ident:
            return i
    for i, h in enumerate(items):
        if ident and ident in str(h.get("name", "")):
            return i
    return None


def _summary(items: list[dict]) -> dict:
    total = sum(float(h.get("amount", 0) or 0) for h in items)
    by_class: dict[str, float] = {}
    for h in items:
        by_class[h.get("asset_class", "其他")] = by_class.get(h.get("asset_class", "其他"), 0) + float(h.get("amount", 0) or 0)
    return {"total": round(total, 2), "by_class": {k: round(v, 2) for k, v in by_class.items()}}


# ── 工具 1：录入 ─────────────────────────────────────────────────────
@tool(
    "add_holding",
    "录入一笔持仓到组合。必填 name(标的名)、asset_class(大类)、amount(当前市值,元)；"
    "选填 code(代码)、sector(行业)、cost(成本,未知填0)、note(备注)，未知传空字符串。"
    "大类取值：股票/股票基金、债券/债基、现金/货基、商品(黄金等)、海外、房产、其他。",
    {"name": str, "asset_class": str, "amount": float,
     "code": str, "sector": str, "cost": float, "note": str},
    annotations=_WRITE,
)
async def add_holding(args: dict) -> dict:
    name = str(args.get("name", "")).strip()
    asset_class = str(args.get("asset_class", "")).strip()
    try:
        amount = float(args.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if not name or amount <= 0:
        return {"content": [{"type": "text", "text": "错误：name 必填、amount 需为正数。"}], "isError": True}

    note_class = "" if asset_class in ASSET_CLASSES else f"（注：大类'{asset_class}'非标准，建议用：{'、'.join(ASSET_CLASSES)}）"
    items = _load()
    cost = float(args.get("cost") or 0)
    rec = {
        "id": _next_id(items),
        "name": name,
        "code": str(args.get("code", "")).strip(),
        "asset_class": asset_class or "其他",
        "sector": str(args.get("sector", "")).strip(),
        "amount": round(amount, 2),
        "cost": round(cost, 2) if cost > 0 else None,
        "currency": str(args.get("currency", "") or "CNY").strip(),
        "note": str(args.get("note", "")).strip(),
        "updated": str(date.today()),
    }
    items.append(rec)
    _save(items)
    s = _summary(items)
    return {"content": [{"type": "text",
            "text": f"已录入 #{rec['id']} {name}（{rec['asset_class']}）市值{rec['amount']}元。"
                    f"当前组合合计 {s['total']} 元，共 {len(items)} 笔。{note_class}"}]}


# ── 工具 2：列出 ─────────────────────────────────────────────────────
@tool(
    "list_holdings",
    "列出当前组合的全部持仓与合计。分析持仓前优先调用它读取已存数据，不要让用户每次重贴。",
    {},
    annotations=_RO,
)
async def list_holdings(args: dict) -> dict:
    items = _load()
    if not items:
        return {"content": [{"type": "text",
                "text": "组合为空。可用 add_holding 录入持仓。"}]}
    s = _summary(items)
    return {"content": [{"type": "text",
            "text": json.dumps({"holdings": items, **s, "count": len(items)}, ensure_ascii=False)}]}


# ── 工具 3：更新 ─────────────────────────────────────────────────────
@tool(
    "update_holding",
    "更新某笔持仓的一个字段（最常见是 amount 市值变动）。identifier 传 id 或标的名；"
    "field 取 name/code/asset_class/sector/amount/cost/currency/note；value 为新值。",
    {"identifier": str, "field": str, "value": str},
    annotations=_WRITE,
)
async def update_holding(args: dict) -> dict:
    identifier = str(args.get("identifier", "")).strip()
    field = str(args.get("field", "")).strip()
    value = str(args.get("value", "")).strip()
    if field not in EDITABLE_FIELDS:
        return {"content": [{"type": "text",
                "text": f"错误：field 须为 {', '.join(EDITABLE_FIELDS)} 之一。"}], "isError": True}
    items = _load()
    idx = _find(items, identifier)
    if idx is None:
        return {"content": [{"type": "text", "text": f"未找到持仓「{identifier}」。"}], "isError": True}
    if field in ("amount", "cost"):
        try:
            items[idx][field] = round(float(value), 2)
        except ValueError:
            return {"content": [{"type": "text", "text": f"错误：{field} 需为数字。"}], "isError": True}
    else:
        items[idx][field] = value
    items[idx]["updated"] = str(date.today())
    _save(items)
    return {"content": [{"type": "text",
            "text": f"已更新 #{items[idx]['id']} {items[idx]['name']} 的 {field} = {items[idx][field]}。"}]}


# ── 工具 4：删除 ─────────────────────────────────────────────────────
@tool(
    "remove_holding",
    "删除一笔持仓（卖出/清仓后）。identifier 传 id 或标的名。",
    {"identifier": str},
    annotations=_DEL,
)
async def remove_holding(args: dict) -> dict:
    identifier = str(args.get("identifier", "")).strip()
    items = _load()
    idx = _find(items, identifier)
    if idx is None:
        return {"content": [{"type": "text", "text": f"未找到持仓「{identifier}」。"}], "isError": True}
    removed = items.pop(idx)
    _save(items)
    return {"content": [{"type": "text",
            "text": f"已删除 #{removed['id']} {removed['name']}。剩余 {len(items)} 笔。"}]}


# ── 工具 5：资产看板（P2，只读分析）──────────────────────────────────
def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


@tool(
    "portfolio_dashboard",
    "生成资产看板：总市值、大类占比、行业占比、现金比例、最大单一持仓、浮动盈亏。"
    "做结构分析/风险诊断/复盘时先调它拿全局画像。",
    {},
    annotations=_RO,
)
async def portfolio_dashboard(args: dict) -> dict:
    items = _load()
    if not items:
        return {"content": [{"type": "text", "text": "组合为空，先用 add_holding 录入持仓。"}]}

    total = sum(float(h.get("amount", 0) or 0) for h in items)

    # 大类分布
    cls: dict[str, float] = {}
    for h in items:
        c = h.get("asset_class", "其他")
        cls[c] = cls.get(c, 0) + float(h.get("amount", 0) or 0)
    by_class = sorted(
        ({"class": k, "amount": round(v, 2), "pct": _pct(v, total)} for k, v in cls.items()),
        key=lambda x: -x["amount"])

    # 行业分布（仅有 sector 的持仓）
    sec: dict[str, float] = {}
    sec_covered = 0.0
    for h in items:
        s = (h.get("sector") or "").strip()
        if s:
            amt = float(h.get("amount", 0) or 0)
            sec[s] = sec.get(s, 0) + amt
            sec_covered += amt
    by_sector = sorted(
        ({"sector": k, "amount": round(v, 2), "pct": _pct(v, total)} for k, v in sec.items()),
        key=lambda x: -x["amount"])

    # 现金比例
    cash = sum(float(h.get("amount", 0) or 0) for h in items if h.get("asset_class") == "现金/货基")

    # 最大单一持仓
    top = max(items, key=lambda h: float(h.get("amount", 0) or 0))

    # 浮动盈亏（仅有成本的持仓）
    cost_items = [h for h in items if h.get("cost")]
    pnl = None
    if cost_items:
        cost_basis = sum(float(h["cost"]) for h in cost_items)
        mv_covered = sum(float(h.get("amount", 0) or 0) for h in cost_items)
        pnl = {
            "cost_basis": round(cost_basis, 2),
            "market_value_covered": round(mv_covered, 2),
            "unrealized_pnl": round(mv_covered - cost_basis, 2),
            "return_pct": _pct(mv_covered - cost_basis, cost_basis),
            "coverage_pct": _pct(mv_covered, total),
        }

    board = {
        "total": round(total, 2),
        "count": len(items),
        "by_class": by_class,
        "by_sector": by_sector,
        "sector_covered_pct": _pct(sec_covered, total),
        "cash_ratio": _pct(cash, total),
        "top_holding": {"name": top.get("name"), "pct": _pct(float(top.get("amount", 0) or 0), total)},
        "pnl": pnl,
    }
    return {"content": [{"type": "text", "text": json.dumps(board, ensure_ascii=False)}]}
