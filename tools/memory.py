"""记忆工具 + 启动加载器（L1 自进化：跨会话记住用户）。

═══════════════════════════════════════════════════════════════════════
对照源码：restored-src/src/services/SessionMemory / extractMemories，
  以及 Claude Code 的 CLAUDE.md / MEMORY.md 机制——我（Claude Code）此刻
  就在用同一套：把事实写成文件，下次会话开头自动读回系统提示。
  LLM 权重不变，"进化"的是这块不断累积的外部记忆。
═══════════════════════════════════════════════════════════════════════

存储：agent_fin/memory/<category>__<key>.md（agent 私有区，不碰你的 Obsidian）。
按 (category, key) upsert——同名直接覆盖，所以"纠正旧信息"天然就是再存一次。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .base import tool

try:
    from mcp.types import ToolAnnotations
    _WRITE = ToolAnnotations(readOnlyHint=False)
    _RO = ToolAnnotations(readOnlyHint=True)
    _DEL = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
except Exception:  # pragma: no cover
    _WRITE = _RO = _DEL = None

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
CATEGORIES = ["用户画像", "持仓", "偏好", "决策", "其他"]
COMMON_TERMS = [
    "低回撤", "回撤", "风险", "风险偏好", "波动", "现金", "债券基金", "债券", "债基",
    "宽基指数", "宽基", "指数", "科技基金", "科技", "黄金", "持仓", "配置", "目标",
    "偏好", "决策", "复盘", "退休", "教育金", "长期", "短期",
]


@dataclass
class MemoryRecord:
    category: str
    key: str
    body: str
    updated: str
    path: Path


# ── 公共辅助 ──────────────────────────────────────────────────────────
def _slug(s: str) -> str:
    return re.sub(r"[^\w一-鿿-]+", "_", str(s).strip())[:50] or "x"


def _path(category: str, key: str) -> Path:
    return MEMORY_DIR / f"{_slug(category)}__{_slug(key)}.md"


def _all_files() -> list[Path]:
    if not MEMORY_DIR.exists():
        return []
    return sorted(MEMORY_DIR.glob("*.md"))


def _parse_record(p: Path) -> MemoryRecord:
    """解析记忆文件。"""
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return MemoryRecord("其他", p.stem, "", "", p)
    cat = key = ""
    updated = ""
    body = text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        fm, body = m.group(1), m.group(2)
        for line in fm.splitlines():
            if line.startswith("category:"):
                cat = line.split(":", 1)[1].strip()
            elif line.startswith("key:"):
                key = line.split(":", 1)[1].strip()
            elif line.startswith("updated:"):
                updated = line.split(":", 1)[1].strip()
    return MemoryRecord(cat or "其他", key or p.stem, body.strip(), updated, p)


def _parse(p: Path) -> tuple[str, str, str]:
    """解析记忆文件 → (category, key, body)。保留给旧调用方。"""
    r = _parse_record(p)
    return r.category, r.key, r.body


def _all_records() -> list[MemoryRecord]:
    return [_parse_record(p) for p in _all_files()]


def _query_terms(query: str) -> list[str]:
    text = str(query or "").strip().lower()
    terms = [t for t in re.split(r"\s+", text) if len(t) >= 2]
    terms.extend(t.lower() for t in COMMON_TERMS if t in text)
    seen = []
    for term in terms:
        if term and term not in seen:
            seen.append(term)
    return seen


def _score(record: MemoryRecord, terms: list[str]) -> int:
    key_blob = f"{record.category} {record.key}".lower()
    body_blob = record.body.lower()
    score = 0
    for term in terms:
        if term in key_blob:
            score += 4
        if term in body_blob:
            score += 2
    return score


def search_memories(query: str, limit: int = 8) -> list[MemoryRecord]:
    terms = _query_terms(query)
    if not terms:
        return []
    hits = []
    for record in _all_records():
        score = _score(record, terms)
        if score:
            hits.append((score, record.updated, record))
    hits.sort(key=lambda x: (-x[0], x[1]), reverse=False)
    return [r for _score_value, _updated, r in hits[: max(1, int(limit or 8))]]


def _format_record(record: MemoryRecord, *, max_body: int = 120) -> str:
    one = " ".join(record.body.split())
    if len(one) > max_body:
        one = one[:max_body] + "…"
    stamp = f" (updated={record.updated})" if record.updated else ""
    return f"[{record.category}/{record.key}]{stamp} {one}"


def load_memory_block(max_items: int = 18, max_body: int = 120) -> str:
    """启动时调用：把全部记忆拼成一段，注入系统提示（≈ 加载 CLAUDE.md）。"""
    records = _all_records()
    if not records:
        return ("\n\n【已记住的用户信息】暂无。随着对话，了解到你的风险画像/持仓/偏好/"
                "重要决策时，我会用 save_memory 记下，下次自动想起。")
    lines = [
        "\n\n【已记住的用户信息】（来自历史会话，自动加载；若与现状不符请直接纠正我）"
    ]
    for record in records[:max_items]:
        lines.append("- " + _format_record(record, max_body=max_body))
    if len(records) > max_items:
        lines.append(f"- 另有 {len(records) - max_items} 条记忆，必要时用 recall_memory 按关键词检索。")
    return "\n".join(lines)


def load_relevant_memory_block(query: str, limit: int = 6) -> str:
    """按当前用户问题取相关记忆，作为本轮额外上下文。"""
    hits = search_memories(query, limit=limit)
    if not hits:
        return ""
    lines = ["\n\n【本轮相关记忆】（按当前问题检索；若与用户当前说法冲突，以当前为准）"]
    lines.extend("- " + _format_record(r, max_body=180) for r in hits)
    return "\n".join(lines)


# ── 工具 1：记住 ─────────────────────────────────────────────────────
@tool(
    "save_memory",
    "把关于用户的持久事实记下来，跨会话生效。category 用 用户画像/持仓/偏好/决策/其他，"
    "key 是简短标识（如 风险等级、目标、现有持仓）。同 category+key 再存即覆盖（用于纠正旧信息）。",
    {"category": str, "key": str, "content": str},
    annotations=_WRITE,
    required=("key", "content"),
)
async def save_memory(args: dict) -> dict:
    category = str(args.get("category", "其他")).strip() or "其他"
    key = str(args.get("key", "")).strip()
    content = str(args.get("content", "")).strip()
    if not key or not content:
        return {"content": [{"type": "text", "text": "错误：key 和 content 不能为空。"}],
                "isError": True}
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(category, key)
    existed = p.exists()
    p.write_text(
        f"---\ncategory: {category}\nkey: {key}\nupdated: {date.today()}\n---\n{content}\n",
        encoding="utf-8",
    )
    verb = "更新" if existed else "记住"
    return {"content": [{"type": "text", "text": f"已{verb} [{category}/{key}]：{content}"}]}


# ── 工具 2：回忆 ─────────────────────────────────────────────────────
@tool(
    "recall_memory",
    "按关键词检索记忆（记多了用它取相关的，比全量回看省）。返回命中的 [分类/键] 与内容。",
    {"query": str},
    annotations=_RO,
)
async def recall_memory(args: dict) -> dict:
    kws = [k for k in re.split(r"\s+", str(args.get("query", "")).strip()) if k]
    if not kws:
        return {"content": [{"type": "text", "text": "错误：query 不能为空。"}], "isError": True}
    limit = int(args.get("limit") or 8)
    hits = search_memories(" ".join(kws), limit=limit)
    if not hits:
        return {"content": [{"type": "text", "text": f"没有匹配「{' '.join(kws)}」的记忆。"}]}
    return {"content": [{"type": "text", "text": "\n".join(
        _format_record(h, max_body=500) for h in hits
    )}]}


@tool(
    "recall_memories",
    "列出当前已记住的全部用户信息。用户问『你还记得我什么』或需要确认画像时调用。",
    {},
    annotations=_RO,
)
async def recall_memories(args: dict) -> dict:
    files = _all_files()
    if not files:
        return {"content": [{"type": "text", "text": "目前还没有任何记忆。"}]}
    blocks = []
    for p in files:
        cat, key, body = _parse(p)
        blocks.append(f"[{cat}/{key}] {body}")
    return {"content": [{"type": "text", "text": "\n".join(blocks)}]}


# ── 工具 3：遗忘 ─────────────────────────────────────────────────────
@tool(
    "forget_memory",
    "删除一条记忆（用户信息过期/错误时）。需提供 category 和 key。",
    {"category": str, "key": str},
    annotations=_DEL,
    required=("category", "key"),
    risk="high",
)
async def forget_memory(args: dict) -> dict:
    category = str(args.get("category", "其他")).strip() or "其他"
    key = str(args.get("key", "")).strip()
    p = _path(category, key)
    if not p.exists():
        return {"content": [{"type": "text", "text": f"没有找到 [{category}/{key}]。"}],
                "isError": True}
    p.unlink()
    return {"content": [{"type": "text", "text": f"已删除 [{category}/{key}]。"}]}
