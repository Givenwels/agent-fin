"""任务计划器（TodoWrite 范式）——让 agent 的"自主规划"显式可见。

═══════════════════════════════════════════════════════════════════════
对照源码：Claude Code 的 TodoWriteTool。面对复杂多步任务，agent 先列计划、
逐步执行、实时更新状态、完成后自检——把"想—做—核"的 agent 行为外化出来，
用户看得见它在规划而非黑箱。这是最"像 agent"的能力之一。
═══════════════════════════════════════════════════════════════════════

计划存 portfolio/plan.json（当前任务用，gitignore；下次新任务覆盖）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
    _WRITE = ToolAnnotations(readOnlyHint=False)
except Exception:  # pragma: no cover
    _RO = _WRITE = None

PLAN_FILE = Path(__file__).resolve().parent.parent / "portfolio" / "plan.json"
_ICON = {"done": "✅", "in_progress": "🔄", "pending": "⬜"}


def _normalize(tasks: list) -> list[dict]:
    out = []
    for t in tasks:
        if isinstance(t, dict):
            step = str(t.get("step", "")).strip()
            status = str(t.get("status", "pending")).strip().lower()
        else:
            step, status = str(t).strip(), "pending"
        if step:
            out.append({"step": step, "status": status if status in _ICON else "pending"})
    return out


def _save(tasks: list[dict]) -> None:
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAN_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def load_plan() -> list[dict]:
    if not PLAN_FILE.exists():
        return []
    try:
        data = json.loads(PLAN_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def render(tasks: list[dict]) -> str:
    if not tasks:
        return "（当前无计划）"
    done = sum(1 for t in tasks if t["status"] == "done")
    lines = [f"{_ICON.get(t['status'], '⬜')} {t['step']}" for t in tasks]
    return f"任务计划（{done}/{len(tasks)} 完成）：\n" + "\n".join(lines)


@tool(
    "write_plan",
    "为复杂的多步任务写/更新执行计划（待办清单）。tasks 是步骤列表，每项 "
    "{step: 步骤描述, status: pending/in_progress/done}。开始多步任务（如一键配置、复盘、调仓）"
    "时先写计划，每完成一步就再调一次更新该步状态——让用户看到你的规划与进度。",
    {"tasks": list},
    annotations=_WRITE,
)
async def write_plan(args: dict) -> dict:
    tasks = _normalize(list(args.get("tasks") or []))
    if not tasks:
        return {"content": [{"type": "text", "text": "错误：tasks 不能为空。"}], "isError": True}
    # 同一时刻最多一个 in_progress，保持清晰
    seen_ip = False
    for t in tasks:
        if t["status"] == "in_progress":
            if seen_ip:
                t["status"] = "pending"
            seen_ip = True
    _save(tasks)
    return {"content": [{"type": "text", "text": render(tasks)}]}
