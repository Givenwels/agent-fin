"""Agent runtime guardrails: context, memory, and tool execution.

These tests are local only. They do not call model APIs and do not touch the
real memory/portfolio directories.
"""

import asyncio

import engine
import tools.memory as memory
from tools.base import ToolDef


def test_compact_messages_preserves_current_user_and_adds_summary():
    import context_manager

    messages = []
    for i in range(16):
        messages.append({"role": "user", "content": f"old question {i} " + "x" * 80})
        messages.append({"role": "assistant", "content": f"old answer {i} " + "y" * 80})
    messages.append({"role": "user", "content": "现在帮我分析我的组合风险"})

    before = len(messages)
    report = context_manager.compact_messages(messages, max_chars=900, keep_recent=4)

    assert report.changed is True
    assert len(messages) < before
    assert messages[0]["role"] == "user"
    assert "历史上下文摘要" in messages[0]["content"]
    assert messages[-1]["content"] == "现在帮我分析我的组合风险"
    assert context_manager.estimate_messages_chars(messages) <= 900


def test_compact_messages_does_not_start_recent_context_with_tool_result():
    import context_manager

    messages = [{"role": "user", "content": "old " + "x" * 4000}]
    messages.extend([
        {"role": "assistant", "content": "准备调用工具", "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "list_holdings", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": "工具结果"},
        {"role": "assistant", "content": "根据工具结果，组合为空。"},
        {"role": "user", "content": "那我该先录入什么？"},
    ])

    context_manager.compact_messages(messages, max_chars=500, keep_recent=3)

    assert messages[1]["role"] != "tool"
    assert messages[-1]["content"] == "那我该先录入什么？"


def test_compact_messages_handles_few_but_large_messages():
    import context_manager

    messages = [
        {"role": "user", "content": "早期问题 " + "x" * 1000},
        {"role": "assistant", "content": "早期回答 " + "y" * 1000},
        {"role": "user", "content": "当前问题要保留"},
    ]

    report = context_manager.compact_messages(messages, max_chars=700, keep_recent=10)

    assert report.changed is True
    assert "历史上下文摘要" in messages[0]["content"]
    assert messages[-1]["content"] == "当前问题要保留"
    assert context_manager.estimate_messages_chars(messages) <= 700


def test_memory_recall_scores_relevant_items_and_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)

    asyncio.run(memory.save_memory.handler({
        "category": "偏好",
        "key": "风险偏好",
        "content": "用户偏好低回撤，不能接受大幅波动。",
    }))
    asyncio.run(memory.save_memory.handler({
        "category": "决策",
        "key": "科技基金",
        "content": "曾经关注科技基金，但尚未决定买入。",
    }))

    result = asyncio.run(memory.recall_memory.handler({"query": "低回撤 风险", "limit": 1}))
    text = result["content"][0]["text"]

    assert "[偏好/风险偏好]" in text
    assert "科技基金" not in text
    assert "updated=" in text


def test_relevant_memory_block_is_query_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)

    asyncio.run(memory.save_memory.handler({
        "category": "偏好",
        "key": "资产偏好",
        "content": "用户喜欢宽基指数和债券基金。",
    }))

    block = memory.load_relevant_memory_block("债券基金怎么配置", limit=3)

    assert "本轮相关记忆" in block
    assert "资产偏好" in block
    assert memory.load_relevant_memory_block("完全无关的问题", limit=3) == ""


def test_execute_tool_truncates_large_output():
    async def big(_args):
        return {"content": [{"type": "text", "text": "x" * 200}]}

    tool = ToolDef("big", "big output", {}, big)
    result = asyncio.run(engine._execute_tool(
        "big", {}, {"big": tool}, max_output_chars=50, timeout_seconds=1
    ))

    assert result.ok is True
    assert result.truncated is True
    assert len(result.text) < 120
    assert "已截断" in result.text


def test_execute_tool_times_out():
    async def slow(_args):
        await asyncio.sleep(0.05)
        return {"content": [{"type": "text", "text": "done"}]}

    tool = ToolDef("slow", "slow output", {}, slow)
    result = asyncio.run(engine._execute_tool(
        "slow", {}, {"slow": tool}, max_output_chars=100, timeout_seconds=0.001
    ))

    assert result.ok is False
    assert result.is_error is True
    assert "超时" in result.text


def test_execute_tool_rejects_missing_required_args():
    async def needs_code(_args):
        return {"content": [{"type": "text", "text": "should not run"}]}

    tool = ToolDef("needs_code", "needs a code", {"code": str}, needs_code)
    result = asyncio.run(engine._execute_tool(
        "needs_code", {}, {"needs_code": tool}, max_output_chars=100, timeout_seconds=1
    ))

    assert result.ok is False
    assert "工具参数错误" in result.text
    assert "code" in result.text


def test_execute_tool_allows_missing_optional_args_when_required_declared():
    seen = {}

    async def capture(args):
        seen.update(args)
        return {"content": [{"type": "text", "text": "ok"}]}

    tool = ToolDef(
        "add_like",
        "required and optional args",
        {"name": str, "note": str, "amount": float},
        capture,
        required=("name", "amount"),
    )
    result = asyncio.run(engine._execute_tool(
        "add_like", {"name": "沪深300ETF", "amount": "1000"},
        {"add_like": tool}, max_output_chars=100, timeout_seconds=1,
    ))

    assert result.ok is True
    assert seen == {"name": "沪深300ETF", "amount": 1000.0}


def test_real_add_holding_allows_optional_fields_to_be_missing(tmp_path, monkeypatch):
    import tools.holdings as holdings

    monkeypatch.setattr(holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    result = asyncio.run(engine._execute_tool(
        "add_holding",
        {"name": "沪深300ETF", "asset_class": "股票/股票基金", "amount": "1000"},
        {"add_holding": holdings.add_holding},
    ))

    assert result.ok is True
    assert "沪深300ETF" in result.text


def test_build_tool_schemas_uses_declared_required_keys():
    async def noop(_args):
        return {"content": [{"type": "text", "text": "ok"}]}

    tool = ToolDef(
        "x_tool",
        "desc",
        {"required_arg": str, "optional_arg": str},
        noop,
        required=("required_arg",),
    )

    schema = engine.build_tool_schemas([tool])[0]

    assert schema["input_schema"]["required"] == ["required_arg"]
    assert "optional_arg" in schema["input_schema"]["properties"]


def test_execute_tool_coerces_simple_scalar_args():
    seen = {}

    async def capture(args):
        seen.update(args)
        return {"content": [{"type": "text", "text": "ok"}]}

    tool = ToolDef("capture", "capture args", {"amount": float, "name": str}, capture)
    result = asyncio.run(engine._execute_tool(
        "capture", {"amount": "3.5", "name": 510300}, {"capture": tool},
        max_output_chars=100, timeout_seconds=1,
    ))

    assert result.ok is True
    assert seen == {"amount": 3.5, "name": "510300"}


def test_execute_tool_denies_high_risk_when_approval_rejects():
    async def destructive(_args):
        return {"content": [{"type": "text", "text": "should not run"}]}

    tool = ToolDef(
        "forget_memory",
        "delete memory",
        {"category": str, "key": str},
        destructive,
        required=("category", "key"),
        risk="high",
    )
    result = asyncio.run(engine._execute_tool(
        "forget_memory",
        {"category": "偏好", "key": "风险"},
        {"forget_memory": tool},
        approval_callback=lambda name, args, tool: (False, "user rejected"),
    ))

    assert result.ok is False
    assert "用户拒绝" in result.text


def test_execute_tool_denies_high_risk_without_approval_callback():
    called = False

    async def destructive(_args):
        nonlocal called
        called = True
        return {"content": [{"type": "text", "text": "should not run"}]}

    tool = ToolDef(
        "remove_holding",
        "delete holding",
        {"identifier": str},
        destructive,
        required=("identifier",),
        risk="high",
    )
    result = asyncio.run(engine._execute_tool(
        "remove_holding",
        {"identifier": "test"},
        {"remove_holding": tool},
    ))

    assert result.ok is False
    assert called is False
    assert "需要用户确认" in result.text


def test_tool_catalog_groups_and_renders_tools():
    import tool_catalog

    rows = tool_catalog.catalog_tools([
        ToolDef("kb_search", "search docs", {"query": str}, lambda _a: None),
        ToolDef("save_memory", "save memory", {"key": str}, lambda _a: None),
        ToolDef(
            "forget_memory", "delete memory", {"category": str, "key": str},
            lambda _a: None, required=("category", "key"), risk="high",
        ),
    ])
    rendered = tool_catalog.render_tool_catalog(rows)

    assert rows[0]["group"] == "知识库"
    assert rows[1]["group"] == "记忆"
    assert rows[1]["risk"] == "high"
    assert "kb_search" in rendered
    assert "key:str" in rendered
    assert "[高风险]" in rendered


def test_trace_state_keeps_recent_events_and_masks_args():
    import trace_state

    trace = trace_state.AgentTrace(max_events=2)
    trace.record(engine.ToolExecution("old_tool", {"api_key": "secret", "x": 1}, "ok", False, 3))
    trace.record(engine.ToolExecution("b", {}, "bad", True, 4))
    trace.record(engine.ToolExecution("c", {}, "long", False, 5, truncated=True))
    rendered = trace.render()

    assert "old_tool" not in rendered
    assert "b" in rendered and "c" in rendered
    assert "secret" not in rendered
    assert "截断" in rendered
