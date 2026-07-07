"""Conversation context management for the local agent loop.

The model context should contain the current task, recent turns, and a compact
trace of older conversation. This module keeps that shape deterministic and
testable without making an extra model call just to summarize history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


DEFAULT_MAX_CONTEXT_CHARS = 30000
DEFAULT_KEEP_RECENT = 18
DEFAULT_SUMMARY_CHARS = 3000


@dataclass
class ContextReport:
    changed: bool
    before_chars: int
    after_chars: int
    summarized_messages: int = 0


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_result":
                    parts.append(str(item.get("content", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)


def estimate_message_chars(message: dict) -> int:
    text = _content_text(message.get("content"))
    extra = ""
    if message.get("tool_calls"):
        extra = json.dumps(message.get("tool_calls"), ensure_ascii=False)
    return len(str(message.get("role", ""))) + len(text) + len(extra)


def estimate_messages_chars(messages: list[dict]) -> int:
    return sum(estimate_message_chars(m) for m in messages)


def context_stats(messages: list[dict]) -> dict:
    return {
        "messages": len(messages),
        "chars": estimate_messages_chars(messages),
    }


def _shorten(text: str, limit: int) -> str:
    one = " ".join(str(text or "").split())
    if len(one) <= limit:
        return one
    return one[: max(0, limit - 1)] + "…"


def _role_label(role: str) -> str:
    return {
        "user": "用户",
        "assistant": "助手",
        "tool": "工具",
    }.get(role, role or "未知")


def summarize_messages(messages: list[dict], max_chars: int = DEFAULT_SUMMARY_CHARS) -> str:
    """Build a compact text summary for older messages."""
    if not messages:
        return ""
    lines = [
        "【历史上下文摘要】以下是较早对话的压缩摘要，用于节省 token；"
        "若摘要与用户当前说法冲突，以当前说法为准。",
    ]
    budget = max(200, max_chars)
    for m in messages[-20:]:
        role = _role_label(str(m.get("role", "")))
        text = _shorten(_content_text(m.get("content")), 180)
        if not text and m.get("tool_calls"):
            names = []
            for call in m.get("tool_calls") or []:
                fn = (call.get("function") or {}) if isinstance(call, dict) else {}
                names.append(fn.get("name", "unknown"))
            text = "调用工具：" + "、".join(names)
        if text:
            lines.append(f"- {role}: {text}")
        if len("\n".join(lines)) >= budget:
            break
    summary = "\n".join(lines)
    return _shorten(summary, budget)


def _safe_recent_start(messages: list[dict], proposed: int) -> int:
    """Avoid starting retained context with a bare tool result."""
    start = max(0, min(proposed, len(messages)))
    while start < len(messages) and messages[start].get("role") == "tool":
        start += 1
    return start


def compact_messages(
    messages: list[dict],
    *,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    summary_chars: int = DEFAULT_SUMMARY_CHARS,
) -> ContextReport:
    """Compact old conversation in-place when it exceeds a character budget."""
    before = estimate_messages_chars(messages)
    if before <= max_chars or len(messages) <= 1:
        return ContextReport(False, before, before, 0)

    recent_count = min(keep_recent, len(messages))
    if len(messages) <= keep_recent:
        recent_count = 1
    start = _safe_recent_start(messages, len(messages) - recent_count)
    old = messages[:start]
    recent = messages[start:]
    summary = summarize_messages(old, max_chars=summary_chars)
    new_messages = ([{"role": "user", "content": summary}] if summary else []) + recent

    while estimate_messages_chars(new_messages) > max_chars and len(recent) > 1:
        recent = recent[1:]
        while recent and recent[0].get("role") == "tool":
            recent = recent[1:]
        new_messages = ([{"role": "user", "content": summary}] if summary else []) + recent

    while estimate_messages_chars(new_messages) > max_chars and summary_chars > 300:
        summary_chars = max(300, summary_chars // 2)
        summary = summarize_messages(old, max_chars=summary_chars)
        new_messages = ([{"role": "user", "content": summary}] if summary else []) + recent

    messages[:] = new_messages
    after = estimate_messages_chars(messages)
    return ContextReport(True, before, after, len(old))
