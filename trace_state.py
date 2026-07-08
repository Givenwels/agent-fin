"""In-memory execution trace for the current REPL session."""

from __future__ import annotations

from collections import deque
from typing import Any

SENSITIVE_KEYS = ("key", "token", "secret", "password", "auth")


def _mask_args(value: Any) -> Any:
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if any(s in str(key).lower() for s in SENSITIVE_KEYS):
                masked[key] = "***"
            else:
                masked[key] = _mask_args(item)
        return masked
    if isinstance(value, list):
        return [_mask_args(v) for v in value[:5]]
    return value


class AgentTrace:
    def __init__(self, max_events: int = 50):
        self.events = deque(maxlen=max_events)

    def record(self, event) -> None:
        self.events.append(event)

    def render(self, limit: int = 10) -> str:
        if not self.events:
            return "本次会话还没有工具调用。"
        rows = list(self.events)[-limit:]
        lines = [f"最近 {len(rows)} 次工具调用："]
        for idx, event in enumerate(rows, 1):
            status = "错误" if event.is_error else "成功"
            flags = []
            if event.truncated:
                flags.append("截断")
            extra = f" · {'/'.join(flags)}" if flags else ""
            args = _mask_args(event.args)
            lines.append(
                f"{idx}. {event.name} · {status} · {event.duration_ms}ms{extra} · args={args}"
            )
        return "\n".join(lines)
