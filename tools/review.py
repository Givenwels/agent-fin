"""周/月复盘报告（P5：第三根支柱"复盘"）。

═══════════════════════════════════════════════════════════════════════
把分散的数据串起来供 agent 写复盘：当前持仓画像 + 风险提示 + 期间投资日记 +
与上次快照的对比（总值变化、配置漂移）。每次复盘存一份当日快照，下次即可对比。
只汇总数据与给方向，不下买卖指令、不承诺收益。
═══════════════════════════════════════════════════════════════════════

快照存 portfolio/snapshots/（已随 portfolio/ gitignore）。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .base import tool

from .holdings import _load as _load_holdings, compute_board
from .journal import _load as _load_journal
from .risk import evaluate_risk

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None

SNAP_DIR = Path(__file__).resolve().parent.parent / "portfolio" / "snapshots"


def _save_snapshot(board: dict) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "date": str(date.today()),
        "total": board["total"],
        "by_class": {c["class"]: c["pct"] for c in board["by_class"]},
        "cash_ratio": board["cash_ratio"],
    }
    (SNAP_DIR / f"{snap['date']}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_prior_snapshot() -> dict | None:
    if not SNAP_DIR.exists():
        return None
    files = sorted(SNAP_DIR.glob("*.json"))
    today = str(date.today())
    prior = [f for f in files if f.stem < today]
    if not prior:
        return None
    try:
        return json.loads(prior[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def _compare(cur: dict, prev: dict) -> dict:
    delta = round(cur["total"] - prev["total"], 2)
    pct = round(delta / prev["total"] * 100, 1) if prev["total"] else 0.0
    drift = {}
    cur_cls = {c["class"]: c["pct"] for c in cur["by_class"]}
    for k in set(cur_cls) | set(prev.get("by_class", {})):
        d = round(cur_cls.get(k, 0) - prev.get("by_class", {}).get(k, 0), 1)
        if abs(d) >= 1:
            drift[k] = d
    return {"prev_date": prev["date"], "total_change": delta,
            "total_change_pct": pct, "class_drift_pct": drift}


def _entries_in_period(days: int) -> list[dict]:
    cutoff = datetime.now().date() - timedelta(days=days)
    out = []
    for e in _load_journal():
        try:
            if datetime.strptime(e.get("date", ""), "%Y-%m-%d").date() >= cutoff:
                out.append(e)
        except ValueError:
            continue
    return out


@tool(
    "review_report",
    "汇总复盘数据：当前持仓画像 + 风险提示 + 期间投资日记 + 与上次快照对比。period_days "
    "传 7(周)/30(月)。返回结构化数据，你据此写一份复盘报告。用户说'帮我做周/月复盘'时调用。",
    {"period_days": int},
    annotations=_RO,
)
async def review_report(args: dict) -> dict:
    items = _load_holdings()
    if not items:
        return {"content": [{"type": "text",
                "text": "组合为空，先录入持仓再复盘。"}]}
    try:
        days = int(args.get("period_days") or 7)
    except (TypeError, ValueError):
        days = 7

    board = compute_board(items)
    risks = evaluate_risk(board)
    journal = _entries_in_period(days)
    prev = _latest_prior_snapshot()
    compare = _compare(board, prev) if prev else None
    _save_snapshot(board)  # 存当日快照，供下次复盘对比

    payload = {
        "period_days": days,
        "as_of": str(date.today()),
        "board": board,
        "compare_vs_last_snapshot": compare,
        "risk_warnings": risks,
        "journal_in_period": journal,
        "journal_count": len(journal),
        "report_sections_hint": [
            "一、本期组合概览（总值、与上次对比、配置漂移）",
            "二、风险体检（结构性风险提示 + 改善方向）",
            "三、本期决策回顾（结合投资日记，逻辑是否兑现/证伪条件是否触发）",
            "四、下期关注点（结合宏观/估值，给方向而非买卖指令）",
        ],
        "disclaimer": "复盘为分析与方向，非个性化投资建议、不构成买卖指令，决策与风险自负。",
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
