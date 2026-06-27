"""待下单清单（调仓单）—— 帮你把"想清楚+算明白"做到最后一步前。

═══════════════════════════════════════════════════════════════════════
读你已存持仓 + 目标配置 → 算出"该买什么、该卖什么、各多少钱"的清单。
你拿这张清单去自己的券商/基金 App 手动下单。
红线：纯计算，不连券商、不下单、不碰账户、不预填表单。最后一步永远是你点。
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json

from claude_agent_sdk import tool

from .holdings import _load

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None


def _match(items: list[dict], key: str):
    """按名称或代码在当前持仓里找一笔，返回 (索引, 持仓) 或 (None, None)。"""
    key = str(key).strip()
    for i, h in enumerate(items):
        if h.get("name") == key or (h.get("code") and h.get("code") == key):
            return i, h
    for i, h in enumerate(items):
        if key and key in str(h.get("name", "")):
            return i, h
    return None, None


@tool(
    "generate_order_list",
    "生成『待下单清单/调仓单』：读已存持仓 + 目标权重，算出每个标的该买/卖多少钱，供你手动下单。"
    "target_weights 形如 {'沪深300ETF':0.4,'国债ETF':0.4,'黄金ETF':0.2}（可用名称或代码做键）；"
    "total_amount 选填(传0=按当前组合总值调仓；传正数=按该总额，相当于加/减仓后的目标规模)。"
    "纯计算，不下单、不碰账户。",
    {"target_weights": dict, "total_amount": float},
    annotations=_RO,
)
async def generate_order_list(args: dict) -> dict:
    tw = dict(args.get("target_weights") or {})
    if not tw:
        return {"content": [{"type": "text", "text": "错误：需要 target_weights（目标权重）。"}],
                "isError": True}
    items = _load()
    current_total = sum(float(h.get("amount", 0) or 0) for h in items)
    try:
        total = float(args.get("total_amount") or 0) or current_total
    except (TypeError, ValueError):
        total = current_total
    if total <= 0:
        return {"content": [{"type": "text",
                "text": "错误：组合为空且未指定 total_amount，无法计算金额。"}], "isError": True}

    # 归一化目标权重
    wsum = sum(float(v) for v in tw.values()) or 1.0
    tw = {k: float(v) / wsum for k, v in tw.items()}

    thresh = max(100.0, total * 0.005)  # 金额变动小于此值视为"保持"，免得为了几十块来回调
    orders, matched_idx = [], set()
    total_buy = total_sell = 0.0

    # 1) 目标里的标的：算与当前的差额
    for key, w in tw.items():
        target_amt = w * total
        idx, h = _match(items, key)
        cur = float(h.get("amount", 0) or 0) if h else 0.0
        if idx is not None:
            matched_idx.add(idx)
        delta = target_amt - cur
        name = h.get("name") if h else key
        code = (h.get("code") if h else "") or ""
        if delta > thresh:
            op = "买入"; total_buy += delta
        elif delta < -thresh:
            op = "卖出"; total_sell += -delta
        else:
            op = "保持"
        orders.append({"标的": name, "代码": code, "操作": op,
                       "金额": round(abs(delta), 0) if op != "保持" else 0,
                       "当前": round(cur, 0), "目标": round(target_amt, 0)})

    # 2) 当前持有但目标里没有的：清仓
    for i, h in enumerate(items):
        if i in matched_idx:
            continue
        cur = float(h.get("amount", 0) or 0)
        if cur > thresh:
            total_sell += cur
            orders.append({"标的": h.get("name"), "代码": h.get("code") or "", "操作": "卖出",
                           "金额": round(cur, 0), "当前": round(cur, 0), "目标": 0})

    payload = {
        "组合总值": round(total, 0),
        "待下单清单": orders,
        "合计买入": round(total_buy, 0),
        "合计卖出": round(total_sell, 0),
        "说明": "这是供你手动执行的『参考调仓清单』。本工具不下单、不连券商、不碰账户——"
                "请在你自己的券商/基金 App 里按当时市价手动操作；金额需按成交价折算份额。"
                "下单完成后可用 update_holding 更新持仓，便于复盘。决策与风险自负。",
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
