"""知识库导航工具（多来源、出处感知；直读笔记，关键词检索，零依赖、离线可用）。

═══════════════════════════════════════════════════════════════════════
对照源码：这三件套就是 Claude Code 浏览代码库的范式搬到「笔记库」上——
  kb_index  ≈ Glob   （列出有哪些来源/文件）
  kb_search ≈ Grep   （关键词跨文件检索，返回命中片段 + 出处）
  kb_read   ≈ Read   （读取整篇原文）
让 agent 像浏览代码一样浏览你的财经笔记：先搜到相关篇 → 再读全文 → 据此作答，
全程不把整库塞进上下文（省 token、不污染、可无限扩充来源）。
═══════════════════════════════════════════════════════════════════════

多来源设计：
  · 「来源」= 知识库根下的顶层子文件夹名（如「汤山老王」），根目录直接放的文件归到根名下。
  · 想加新来源：在知识库文件夹里新建一个子文件夹（如「霍华德马克斯」「达里奥」「书籍」）放笔记即可，
    自动被索引、自动带出处——不局限于任何单一作者。
  · FIN_KB_DIR 支持多个根，用 ; 或 , 分隔（如把「财经」和「书摘」两个文件夹都纳入）。
默认排除 25年/26年/raw 这类带时间戳的原始字幕（实时观点，会污染检索）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .base import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None

# ── 配置 ──────────────────────────────────────────────────────────────
DEFAULT_KB_DIR = r"F:\笔记obsinlin\随便写\学习\财经"
EXCLUDE_DIRS = {"25年", "26年", "raw"}  # 原始字幕/实时原文，默认不进检索
MAX_READ_CHARS = 8_000  # 上下文控制：单次返回上限，超了截断并提示取小节


def _headings(text: str) -> list[str]:
    return [ln.strip().lstrip("#").strip()
            for ln in text.splitlines() if ln.lstrip().startswith("#")]


def _extract_section(text: str, section: str) -> str | None:
    """取标题包含 section 的那一节（从该标题到下一个同/更高级标题）。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#") and section in ln:
            start = i
            level = len(ln) - len(ln.lstrip("#").lstrip())  # 粗略层级
            break
    if start is None:
        return None
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.lstrip().startswith("#"):
            lv = len(ln) - len(ln.lstrip("#").lstrip())
            if lv <= level:
                break
        out.append(ln)
    return "\n".join(out).strip()


def _kb_roots() -> list[Path]:
    """知识库根目录列表（FIN_KB_DIR 支持用 ; 或 , 分隔多个根）。"""
    raw = os.environ.get("FIN_KB_DIR", DEFAULT_KB_DIR)
    return [Path(p.strip()) for p in re.split(r"[;,]", raw) if p.strip()]


# ── 公共辅助 ──────────────────────────────────────────────────────────
def _included_files() -> list[tuple[Path, Path]]:
    """枚举参与检索的笔记，返回 [(文件, 所属根), ...]（排除原文目录）。"""
    out: list[tuple[Path, Path]] = []
    for root in _kb_roots():
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            parts = p.relative_to(root).parts
            if any(part in EXCLUDE_DIRS for part in parts):
                continue
            out.append((p, root))
    return sorted(out, key=lambda x: str(x[0]))


def _source_of(p: Path, root: Path) -> str:
    """出处 = 根下顶层子文件夹名；根目录直接放的文件归到根名下。"""
    rel = p.relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else root.name


def _rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _title(p: Path) -> str:
    """取第一条 H1 作标题，跳过 front-matter。"""
    lines = _read(p).splitlines()
    i = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                i = j + 1
                break
    for line in lines[i:]:
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return p.stem


# ── 工具 1：知识目录（按来源分组）────────────────────────────────────
@tool(
    "kb_index",
    "列出财经知识库的全部来源与笔记（按来源/作者分组）。想了解知识库覆盖哪些作者、"
    "哪些主题，或不确定该读哪篇时先调用它。",
    {},
    annotations=_RO,
)
async def kb_index(args: dict) -> dict:
    files = _included_files()
    if not files:
        roots = "; ".join(str(r) for r in _kb_roots())
        return {"content": [{"type": "text",
                "text": f"知识库为空或路径不存在：{roots}（可设环境变量 FIN_KB_DIR 指定，多个根用 ; 分隔）。"}],
                "isError": True}
    groups: dict[str, list[dict]] = {}
    for p, root in files:
        src = _source_of(p, root)
        groups.setdefault(src, []).append({"note": _rel(p, root), "title": _title(p)})
    sources = [{"source": s, "count": len(v), "notes": v} for s, v in groups.items()]
    return {"content": [{"type": "text",
            "text": json.dumps({"total": len(files), "source_count": len(sources),
                                "sources": sources}, ensure_ascii=False)}]}


# ── 工具 2：关键词检索（带出处）──────────────────────────────────────
@tool(
    "kb_search",
    "在财经知识库里按关键词跨来源检索（空格分隔多词，命中越多排越前），返回命中的"
    "来源、笔记、小节标题与上下文片段。回答具体概念/宏观/利率问题前用它定位原文。",
    {"query": str},
    annotations=_RO,
)
async def kb_search(args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    kws = [k for k in re.split(r"\s+", query) if k]
    if not kws:
        return {"content": [{"type": "text", "text": "错误：query 不能为空。"}], "isError": True}

    # 按 (笔记, 小节) 聚合，取命中数最高的若干段
    buckets: dict[tuple[str, str], dict] = {}
    for p, root in _included_files():
        src = _source_of(p, root)
        rel = _rel(p, root)
        lines = _read(p).splitlines()
        cur_head = "(开头)"
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                cur_head = line.strip("# ").strip() or cur_head
                continue
            low = line.lower()
            hits = sum(1 for k in kws if k.lower() in low)
            if hits == 0:
                continue
            key = (rel, cur_head)
            ctx = "\n".join(lines[max(0, idx - 1): idx + 2]).strip()
            b = buckets.get(key)
            if b is None:
                buckets[key] = {"source": src, "note": rel, "section": cur_head,
                                "score": hits, "snippet": ctx}
            else:
                b["score"] += hits

    if not buckets:
        return {"content": [{"type": "text",
                "text": f"未命中「{query}」。可先用 kb_index 看有哪些来源/主题，或换关键词。"}]}

    top = sorted(buckets.values(), key=lambda b: -b["score"])[:8]
    return {"content": [{"type": "text",
            "text": json.dumps({"query": query, "hits": top,
                                "tip": "用 kb_read(note) 读整篇；引用时务必注明 source 出处"},
                               ensure_ascii=False)}]}


# ── 工具 3：读取整篇 ─────────────────────────────────────────────────
@tool(
    "kb_read",
    "读取知识库某篇笔记。note 传相对路径/文件名/标题关键字。section 选填：传某小节标题关键字"
    "只取那一节（省上下文，优先用）；不传则返回全文（过长会截断并列出小节，再按小节取）。",
    {"note": str, "section": str},
    annotations=_RO,
)
async def kb_read(args: dict) -> dict:
    note = str(args.get("note", "")).strip()
    section = str(args.get("section", "")).strip()
    if not note:
        return {"content": [{"type": "text", "text": "错误：note 不能为空。"}], "isError": True}

    files = _included_files()
    target: tuple[Path, Path] | None = None
    # 1) 精确匹配 相对路径/文件名/stem
    for p, root in files:
        if note in (_rel(p, root), p.name, p.stem):
            target = (p, root)
            break
    # 2) 模糊匹配 stem/标题
    if target is None:
        for p, root in files:
            if note.lower() in p.stem.lower() or note in _title(p):
                target = (p, root)
                break

    if target is None:
        avail = "; ".join(_rel(p, root) for p, root in files[:20])
        return {"content": [{"type": "text",
                "text": f"未找到「{note}」。可选笔记：{avail}"}], "isError": True}

    p, root = target
    # 安全：确保仍在某个知识库根内（防路径穿越）
    try:
        p.resolve().relative_to(root.resolve())
    except ValueError:
        return {"content": [{"type": "text", "text": "错误：越界访问被拒绝。"}], "isError": True}

    full = _read(p)
    header = f"# 出处：{_source_of(p, root)} · {_rel(p, root)}\n\n"

    # 指定小节：只取那一节（最省上下文）
    if section:
        sec = _extract_section(full, section)
        if sec is None:
            hs = "；".join(_headings(full)[:20])
            return {"content": [{"type": "text",
                    "text": f"未找到小节「{section}」。本篇小节有：{hs}"}], "isError": True}
        text = sec[:MAX_READ_CHARS] + ("\n\n[...小节过长已截断...]" if len(sec) > MAX_READ_CHARS else "")
        return {"content": [{"type": "text", "text": header + text}]}

    # 全文：过长则截断并列出小节，引导按小节取
    if len(full) > MAX_READ_CHARS:
        hs = "；".join(_headings(full)[:25])
        text = (full[:MAX_READ_CHARS]
                + f"\n\n[...全文较长已截断。要看后续，用 kb_read(note, section='小节标题')。"
                  f"本篇小节：{hs}]")
        return {"content": [{"type": "text", "text": header + text}]}
    return {"content": [{"type": "text", "text": header + full}]}
