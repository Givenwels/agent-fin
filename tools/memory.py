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


# ── 公共辅助 ──────────────────────────────────────────────────────────
def _slug(s: str) -> str:
    return re.sub(r"[^\w一-鿿-]+", "_", str(s).strip())[:50] or "x"


def _path(category: str, key: str) -> Path:
    return MEMORY_DIR / f"{_slug(category)}__{_slug(key)}.md"


def _all_files() -> list[Path]:
    if not MEMORY_DIR.exists():
        return []
    return sorted(MEMORY_DIR.glob("*.md"))


def _parse(p: Path) -> tuple[str, str, str]:
    """解析记忆文件 → (category, key, body)。"""
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return "其他", p.stem, ""
    cat = key = ""
    body = text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        fm, body = m.group(1), m.group(2)
        for line in fm.splitlines():
            if line.startswith("category:"):
                cat = line.split(":", 1)[1].strip()
            elif line.startswith("key:"):
                key = line.split(":", 1)[1].strip()
    return cat or "其他", key or p.stem, body.strip()


def load_memory_block() -> str:
    """启动时调用：把全部记忆拼成一段，注入系统提示（≈ 加载 CLAUDE.md）。"""
    files = _all_files()
    if not files:
        return ("\n\n【已记住的用户信息】暂无。随着对话，了解到你的风险画像/持仓/偏好/"
                "重要决策时，我会用 save_memory 记下，下次自动想起。")
    lines = ["\n\n【已记住的用户信息】（来自历史会话，自动加载；若与现状不符请直接纠正我）"]
    for p in files:
        cat, key, body = _parse(p)
        one = " ".join(body.split())
        if len(one) > 120:
            one = one[:120] + "…"
        lines.append(f"- [{cat}/{key}] {one}")
    return "\n".join(lines)


# ── 工具 1：记住 ─────────────────────────────────────────────────────
@tool(
    "save_memory",
    "把关于用户的持久事实记下来，跨会话生效。category 用 用户画像/持仓/偏好/决策/其他，"
    "key 是简短标识（如 风险等级、目标、现有持仓）。同 category+key 再存即覆盖（用于纠正旧信息）。",
    {"category": str, "key": str, "content": str},
    annotations=_WRITE,
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
    hits = []
    for p in _all_files():
        cat, key, body = _parse(p)
        blob = f"{cat} {key} {body}".lower()
        score = sum(1 for k in kws if k.lower() in blob)
        if score:
            hits.append((score, f"[{cat}/{key}] {body}"))
    if not hits:
        return {"content": [{"type": "text", "text": f"没有匹配「{' '.join(kws)}」的记忆。"}]}
    hits.sort(key=lambda x: -x[0])
    return {"content": [{"type": "text", "text": "\n".join(h[1] for h in hits[:8])}]}


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
