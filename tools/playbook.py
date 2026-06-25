"""流程加载器（一键资产配置流水线的"触发器"）。

═══════════════════════════════════════════════════════════════════════
对照源码：restored-src/src/skills/ + SkillTool——技能不是写死在提示词里，
  而是"按需加载"：触发时把流程文本喂给模型，模型再自主按步骤执行。
  这样既保证流程严谨（每步该调哪个工具写清楚），又不污染日常对话的上下文。
  start_allocation 就是把 playbooks/allocation.md 这套流程加载进来。
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None

PLAYBOOK_DIR = Path(__file__).resolve().parent.parent / "playbooks"


@tool(
    "start_allocation",
    "启动『一键大类资产配置』标准流程。当用户要做完整资产配置、要一份配置方案、说"
    "『帮我配一下/给个配置建议』时调用：返回 8 步流程，随后你要按步骤用其它工具自主执行。",
    {},
    annotations=_RO,
)
async def start_allocation(args: dict) -> dict:
    p = PLAYBOOK_DIR / "allocation.md"
    if not p.exists():
        return {"content": [{"type": "text",
                "text": f"错误：找不到流程文件 {p}。"}], "isError": True}
    text = p.read_text(encoding="utf-8")
    return {"content": [{"type": "text",
            "text": "已加载『一键资产配置』流程，请从第 1 步开始逐步执行：\n\n" + text}]}


@tool(
    "decision_checklist",
    "加载『投资决策 Checklist』。当用户要买入/卖出某资产、或问'这笔该不该买/卖'时调用，"
    "随后按清单逐项追问，帮用户把冲动决策变成有纪律的决策，走完建议记 add_journal。",
    {},
    annotations=_RO,
)
async def decision_checklist(args: dict) -> dict:
    p = PLAYBOOK_DIR / "decision_checklist.md"
    if not p.exists():
        return {"content": [{"type": "text", "text": f"错误：找不到清单文件 {p}。"}], "isError": True}
    text = p.read_text(encoding="utf-8")
    return {"content": [{"type": "text",
            "text": "已加载『投资决策 Checklist』，请逐项追问用户（不要一次甩完）：\n\n" + text}]}
