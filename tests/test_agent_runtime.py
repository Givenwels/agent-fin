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
