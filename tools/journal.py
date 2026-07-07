"""投资日记（P4：决策闭环的记录端 —— 让 agent 能"复盘"的前提）。

═══════════════════════════════════════════════════════════════════════
记录每次买入/卖出/调仓/观察的"当时怎么想"，是日后复盘的素材。
配合 decision_checklist：决策前走清单 → 决策后记日记 → 周/月复盘回看，闭环。
═══════════════════════════════════════════════════════════════════════

存储：portfolio/journal.json（已 gitignore，纯本地）。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .base import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
    _WRITE = ToolAnnotations(readOnlyHint=False)
except Exception:  # pragma: no cover
    _RO = _WRITE = None

JOURNAL_DIR = Path(__file__).resolve().parent.parent / "portfolio"
JOURNAL_FILE = JOURNAL_DIR / "journal.json"

ENTRY_TYPES = ["买入", "卖出", "调仓", "观察", "复盘", "其它"]


def _load() -> list[dict]:
    if not JOURNAL_FILE.exists():
        return []
    try:
        data = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    JOURNAL_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


@tool(
    "add_journal",
    "记一条投资日记。type 取 买入/卖出/调仓/观察/复盘/其它；content 写当时的理由与判断；"
    "title 选填(一句话标题)，related 选填(相关标的)。决策后应主动记一条，便于日后复盘。",
    {"type": str, "content": str, "title": str, "related": str},
    annotations=_WRITE,
)
async def add_journal(args: dict) -> dict:
    typ = str(args.get("type", "")).strip() or "其它"
    content = str(args.get("content", "")).strip()
    if not content:
        return {"content": [{"type": "text", "text": "错误：content 不能为空。"}], "isError": True}
    items = _load()
    rec = {
        "id": max((int(e.get("id", 0)) for e in items), default=0) + 1,
        "date": str(date.today()),
        "type": typ if typ in ENTRY_TYPES else "其它",
        "title": str(args.get("title", "")).strip(),
        "content": content,
        "related": str(args.get("related", "")).strip(),
    }
    items.append(rec)
    _save(items)
    return {"content": [{"type": "text",
            "text": f"已记日记 #{rec['id']}（{rec['date']} {rec['type']}）：{rec['title'] or content[:30]}"}]}


@tool(
    "list_journal",
    "列出最近的投资日记（默认最近 15 条）。limit 指定条数；复盘时用它回看历史决策。",
    {"limit": int},
    annotations=_RO,
)
async def list_journal(args: dict) -> dict:
    items = _load()
    if not items:
        return {"content": [{"type": "text", "text": "暂无投资日记。决策后可用 add_journal 记录。"}]}
    try:
        limit = int(args.get("limit") or 15)
    except (TypeError, ValueError):
        limit = 15
    recent = items[-limit:]
    return {"content": [{"type": "text",
            "text": json.dumps({"count": len(items), "showing": len(recent), "entries": recent},
                               ensure_ascii=False)}]}
