"""Agent capability and readiness reporting tests."""

from __future__ import annotations

import asyncio

from tools.base import ToolDef


async def _ok_handler(_args):
    return {"content": [{"type": "text", "text": "ok"}]}


def _tool(name: str, *, risk: str = "low") -> ToolDef:
    return ToolDef(name, "test tool", {}, _ok_handler, risk=risk)


def test_agent_profile_counts_tools_and_masks_api_secret():
    import agent_profile

    env = {
        "FIN_API_PROVIDER": "codex",
        "OPENAI_MODEL": "deepseek-v4-flash",
        "OPENAI_API_KEY": "unit-test-token-abcdef",
    }
    profile = agent_profile.build_agent_profile(
        tools=[_tool("list_holdings"), _tool("forget_memory", risk="high")],
        env=env,
        messages=[{"role": "user", "content": "hello"}],
        stats={"turns": 2, "tokens": 120},
    )
    rendered = agent_profile.render_agent_profile(profile)

    assert profile["tool_count"] == 2
    assert profile["high_risk_tool_count"] == 1
    assert profile["api"]["configured"] is True
    assert "unit-test-token-abcdef" not in rendered
    assert "Claude Code" in rendered
    assert "NO_AUTO_ORDER" in rendered


def test_agent_doctor_reports_missing_api_without_calling_network(tmp_path):
    import agent_profile

    report = agent_profile.build_agent_doctor(
        tools=[_tool("list_holdings")],
        env={"FIN_API_PROVIDER": "codex"},
        root=tmp_path,
        stats={"turns": 0, "tokens": 0},
    )
    rendered = agent_profile.render_agent_doctor(report)

    api_check = next(check for check in report["checks"] if check["id"] == "api")
    assert api_check["status"] == "WARN"
    assert "network: not called" in rendered
    assert "OPENAI_API_KEY" in rendered


def test_agent_self_check_tool_returns_capability_text():
    from tools.agent_status import agent_self_check

    result = asyncio.run(agent_self_check.handler({"mode": "capabilities"}))
    text = result["content"][0]["text"]

    assert "Fin Agent" in text
    assert "Claude Code" in text
    assert "NO_AUTO_ORDER" in text
