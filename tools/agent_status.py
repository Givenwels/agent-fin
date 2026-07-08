"""Agent self-inspection tools."""

from __future__ import annotations

from .base import tool


@tool(
    "agent_self_check",
    "查看当前 Agent 的能力画像或运行体检；用于回答用户问'你现在能做什么/状态怎样'。",
    {"mode": str},
    required=(),
)
async def agent_self_check(args: dict) -> dict:
    import agent_profile
    from tools import ALL_TOOLS

    mode = str(args.get("mode") or "doctor").strip().lower()
    if mode in ("capabilities", "capability", "profile", "agent"):
        profile = agent_profile.build_agent_profile(tools=ALL_TOOLS)
        text = agent_profile.render_agent_profile(profile)
    else:
        report = agent_profile.build_agent_doctor(tools=ALL_TOOLS)
        text = agent_profile.render_agent_doctor(report)
    return {"content": [{"type": "text", "text": text}]}
