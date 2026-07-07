"""自写 Agent 循环——本项目的心脏（对照 Claude Code 的 query.ts）。

不再依赖 claude-agent-sdk 的运行时（那套底层会拉起 `claude` 子进程当引擎）。
这里默认用 OpenAI SDK 接 Codex/OpenAI provider，同时保留 Anthropic-compatible
provider，自己驱动这条循环：

    模型输出 → 若要求 tool_use → 本地执行工具 → 把 tool_result 塞回 → 再问模型
    → 直到模型不再要工具、给出最终回答（stop_reason != "tool_use"）。

工具复用 tools/ 里用 @tool 定义好的对象（暴露 .name/.description/.input_schema/
.handler），无需改动任何业务逻辑。

工具执行层提供超时、输出截断和结构化事件，避免单个工具拖死回合或把上下文撑爆。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from tools import ALL_TOOLS

# 简化 input_schema（{"key": python_type}）→ JSON Schema 类型
_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

DEFAULT_MAX_TOKENS = 4096
DEFAULT_TOOL_TIMEOUT_SECONDS = 30.0
DEFAULT_TOOL_OUTPUT_CHARS = 6000


@dataclass
class AgentClient:
    """Provider-aware API client wrapper."""
    provider: str
    raw: Any

    async def close(self) -> None:
        close = getattr(self.raw, "close", None)
        if close:
            await close()


@dataclass
class ToolExecution:
    """A single local tool execution event."""
    name: str
    args: dict
    text: str
    is_error: bool
    duration_ms: int
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.is_error


def build_tool_schemas(tools) -> list[dict]:
    """把 @tool 对象列表转成 Anthropic Messages API 的 tools 参数。"""
    schemas = []
    for t in tools:
        props, required = {}, []
        for key, pytype in (getattr(t, "input_schema", None) or {}).items():
            props[key] = {"type": _JSON_TYPE.get(pytype, "string")}
            required.append(key)
        schemas.append({
            "name": t.name,
            "description": t.description,
            "input_schema": {"type": "object", "properties": props, "required": required},
        })
    return schemas


TOOLS_SCHEMA = build_tool_schemas(ALL_TOOLS)
TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS}

# 合成工具：把子任务委派给领域子 agent（≈ Claude Code 的 Task 工具）。
# 只在主循环里提供（allow_delegate=True），子 agent 内部不提供，避免无限递归。
DELEGATE_TOOL = {
    "name": "delegate",
    "description": (
        "把一个子任务委派给领域子 agent，由它在受限工具集内独立完成并返回结论。"
        "agent 取：macro-analyst(判断当前宏观环境/给大类倾向)、"
        "risk-profiler(风险测评，输出风险等级与股债比例区间)、"
        "allocator(在给定风险/宏观下用数据与优化工具产出参考配置)。"
        "task 写清要它做什么、已知的前提（如风险等级、候选标的）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {"agent": {"type": "string"}, "task": {"type": "string"}},
        "required": ["agent", "task"],
    },
}


def _ensure_ssl_cert() -> None:
    """有的 conda 环境把 SSL_CERT_FILE 指到不存在的文件，导致 httpx 建 SSL 上下文失败。
    指向缺失时退回 certifi 自带证书。"""
    f = os.environ.get("SSL_CERT_FILE")
    if f and not os.path.exists(f):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            os.environ.pop("SSL_CERT_FILE", None)


def model_name() -> str:
    if provider_name() == "codex":
        return os.environ.get("OPENAI_MODEL") or os.environ.get("CODEX_MODEL") or "gpt-5.1"
    return os.environ.get("ANTHROPIC_MODEL") or "claude-3-5-sonnet-latest"


def provider_name() -> str:
    raw = (os.environ.get("FIN_API_PROVIDER") or os.environ.get("AGENT_API_PROVIDER") or "").strip().lower()
    if raw in ("codex", "openai"):
        return "codex"
    if raw in ("anthropic", "anthropic-compatible"):
        return "anthropic"
    # Codex/OpenAI is the default path now. Keep Anthropic-compatible endpoints
    # available, but only when explicitly selected through FIN_API_PROVIDER.
    return "codex"


def build_client() -> AgentClient:
    """按环境变量构造 provider 客户端。

    FIN_API_PROVIDER=codex 使用 OpenAI SDK（OPENAI_API_KEY/OPENAI_MODEL）；
    anthropic 兼容端点继续使用 anthropic SDK（ANTHROPIC_*）。
    """
    _ensure_ssl_cert()
    provider = provider_name()
    if provider == "codex":
        try:
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError("未安装 openai SDK，请先运行：pip install -r requirements.txt") from e
        kwargs: dict = {}
        base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("CODEX_BASE_URL")
        if base:
            kwargs["base_url"] = base
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY")
        if key:
            kwargs["api_key"] = key
        return AgentClient(provider="codex", raw=AsyncOpenAI(**kwargs))

    try:
        import anthropic
    except Exception as e:
        raise RuntimeError("未安装 anthropic SDK，请先运行：pip install -r requirements.txt") from e
    kwargs: dict = {}
    base = os.environ.get("ANTHROPIC_BASE_URL")
    if base:
        kwargs["base_url"] = base
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        kwargs["auth_token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    elif os.environ.get("ANTHROPIC_API_KEY"):
        kwargs["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    return AgentClient(provider="anthropic", raw=anthropic.AsyncAnthropic(**kwargs))


def _blocks_to_dicts(content) -> list[dict]:
    """把响应里的内容块转成纯 dict（既是合法的 API 入参，又能 JSON 持久化做 -c 续接）。"""
    out = []
    for b in content:
        t = getattr(b, "type", None)
        if t == "text":
            out.append({"type": "text", "text": b.text})
        elif t == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        # 其它块类型（如 thinking）对工具循环的上下文正确性非必需，忽略
    return out


def _tool_timeout_seconds() -> float:
    try:
        return float(os.environ.get("FIN_TOOL_TIMEOUT_SECONDS") or DEFAULT_TOOL_TIMEOUT_SECONDS)
    except Exception:
        return DEFAULT_TOOL_TIMEOUT_SECONDS


def _tool_output_chars() -> int:
    try:
        return int(os.environ.get("FIN_TOOL_OUTPUT_CHARS") or DEFAULT_TOOL_OUTPUT_CHARS)
    except Exception:
        return DEFAULT_TOOL_OUTPUT_CHARS


def _extract_tool_text(result: dict) -> str:
    content = (result or {}).get("content") or []
    if not content:
        return ""
    first = content[0] if isinstance(content, list) else content
    if isinstance(first, dict):
        return str(first.get("text", ""))
    return str(first)


def _limit_tool_text(text: str, max_chars: int) -> tuple[str, bool]:
    text = str(text or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    suffix = f"\n\n[工具输出过长，已截断到 {max_chars} 字符；如需完整内容，请缩小查询范围或导出报告。]"
    keep = max(0, max_chars - len(suffix))
    return text[:keep] + suffix, True


async def _execute_tool(
    name: str,
    args: dict,
    tool_by_name: dict,
    *,
    max_output_chars: int | None = None,
    timeout_seconds: float | None = None,
) -> ToolExecution:
    """Execute one tool with timeout, truncation, and structured telemetry."""
    t0 = time.perf_counter()
    tool = tool_by_name.get(name)
    if tool is None:
        return ToolExecution(name, args or {}, f"未知工具：{name}", True, 0)
    try:
        timeout = _tool_timeout_seconds() if timeout_seconds is None else timeout_seconds
        res = await asyncio.wait_for(tool.handler(args or {}), timeout=timeout)
        text = _extract_tool_text(res)
        text, truncated = _limit_tool_text(
            text,
            _tool_output_chars() if max_output_chars is None else max_output_chars,
        )
        dur = int((time.perf_counter() - t0) * 1000)
        return ToolExecution(name, args or {}, text, bool(res.get("isError")), dur, truncated)
    except asyncio.TimeoutError:
        dur = int((time.perf_counter() - t0) * 1000)
        return ToolExecution(name, args or {}, f"工具执行超时：{name}", True, dur)
    except Exception as e:
        dur = int((time.perf_counter() - t0) * 1000)
        return ToolExecution(name, args or {}, f"工具执行出错：{type(e).__name__}: {e}", True, dur)


async def _run_tool(name: str, args: dict, tool_by_name: dict) -> tuple[str, bool]:
    """执行一个工具，返回（文本结果, 是否出错）。"""
    result = await _execute_tool(name, args, tool_by_name)
    return result.text, result.is_error


async def run_turn(
    client,
    system: str,
    messages: list[dict],
    on_text=None,
    on_tool=None,
    on_tool_result=None,
    *,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    tools_schema: list[dict] | None = None,
    tool_by_name: dict | None = None,
    allow_delegate: bool = False,
    max_iters: int = 16,
) -> dict:
    """跑完一个用户回合（含任意多轮 tool_use 循环）。原地 append 到 messages。

    on_text(str)  每个模型文本回合的整段文本（非流式）。
    on_tool(str)  每次发起一个工具调用时的工具名。
    tools_schema / tool_by_name  默认用全量 fin 工具；子 agent 传受限子集。
    allow_delegate  主循环传 True，额外提供 delegate 工具委派子 agent。
    max_iters  工具回合上限（≈ Claude Code 的 turn 限额），防止失控循环；
               到上限时最后一次不带工具再问，逼模型给出文本结论。
    返回 {"input_tokens": int, "output_tokens": int}（本回合累计）。
    """
    if isinstance(client, AgentClient) and client.provider == "codex":
        return await _run_turn_codex(
            client, client.raw, system, messages, on_text, on_tool,
            on_tool_result=on_tool_result,
            model=model, max_tokens=max_tokens,
            tools_schema=tools_schema, tool_by_name=tool_by_name,
            allow_delegate=allow_delegate, max_iters=max_iters,
        )

    raw_client = client.raw if isinstance(client, AgentClient) else client
    model = model or model_name()
    schema = TOOLS_SCHEMA if tools_schema is None else tools_schema
    by_name = TOOL_BY_NAME if tool_by_name is None else tool_by_name
    if allow_delegate:
        schema = schema + [DELEGATE_TOOL]
    total_in = total_out = 0
    iters = 0

    while True:
        iters += 1
        use_tools = iters <= max_iters  # 超限则本轮不给工具，强制收口给文本
        kwargs = dict(model=model, system=system, messages=messages, max_tokens=max_tokens)
        if use_tools and schema:
            kwargs["tools"] = schema
        resp = await raw_client.messages.create(**kwargs)
        u = resp.usage
        total_in += getattr(u, "input_tokens", 0) or 0
        total_out += getattr(u, "output_tokens", 0) or 0

        if on_text:
            txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            if txt:
                on_text(txt)

        messages.append({"role": "assistant", "content": _blocks_to_dicts(resp.content)})

        if not use_tools or resp.stop_reason != "tool_use":
            return {"input_tokens": total_in, "output_tokens": total_out}

        # 执行本轮模型要求的所有工具，把结果作为一条 user(tool_result) 消息塞回
        results = []
        for b in resp.content:
            if getattr(b, "type", None) != "tool_use":
                continue
            if allow_delegate and b.name == "delegate":
                agent = (b.input or {}).get("agent", "")
                if on_tool:
                    on_tool(f"delegate→{agent}")
                t0 = time.perf_counter()
                text = await run_subagent(client, agent, (b.input or {}).get("task", ""),
                                          on_tool=on_tool, model=model)
                is_err = False
                if on_tool_result:
                    on_tool_result(ToolExecution(
                        f"delegate→{agent}", b.input or {}, text, False,
                        int((time.perf_counter() - t0) * 1000),
                    ))
            else:
                if on_tool:
                    on_tool(b.name)
                result = await _execute_tool(b.name, b.input, by_name)
                text, is_err = result.text, result.is_error
                if on_tool_result:
                    on_tool_result(result)
            results.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": text,
                "is_error": is_err,
            })
        messages.append({"role": "user", "content": results})


def _to_openai_tools(schema: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool schemas to OpenAI Chat Completions tools."""
    out = []
    for item in schema:
        if item.get("type") == "function" and "function" in item:
            out.append(item)
            continue
        out.append({
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item.get("description", ""),
                "parameters": item.get("input_schema") or {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        })
    return out


def _messages_to_openai(messages: list[dict]) -> list[dict]:
    """Normalize saved mixed-format history into OpenAI chat messages."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "tool":
            out.append(m)
            continue
        if role == "assistant" and "tool_calls" in m:
            out.append(m)
            continue
        if role == "assistant":
            if isinstance(content, list):
                text = "".join(b.get("text", "") for b in content
                               if isinstance(b, dict) and b.get("type") == "text")
            else:
                text = str(content or "")
            out.append({"role": "assistant", "content": text})
            continue
        if role == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": b.get("tool_use_id", ""),
                        "content": str(b.get("content", "")),
                    })
            continue
        if role in ("system", "user"):
            out.append({"role": role, "content": str(content or "")})
    return out


def _json_args(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _run_turn_codex(
    provider_client: AgentClient,
    client,
    system: str,
    messages: list[dict],
    on_text=None,
    on_tool=None,
    on_tool_result=None,
    *,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    tools_schema: list[dict] | None = None,
    tool_by_name: dict | None = None,
    allow_delegate: bool = False,
    max_iters: int = 16,
) -> dict:
    """OpenAI/Codex provider loop using Chat Completions function calling."""
    model = model or model_name()
    schema = TOOLS_SCHEMA if tools_schema is None else tools_schema
    by_name = TOOL_BY_NAME if tool_by_name is None else tool_by_name
    if allow_delegate:
        schema = schema + [DELEGATE_TOOL]
    tools = _to_openai_tools(schema)
    total_in = total_out = 0
    iters = 0

    while True:
        iters += 1
        use_tools = iters <= max_iters
        chat_messages = [{"role": "system", "content": system}] + _messages_to_openai(messages)
        kwargs = dict(model=model, messages=chat_messages)
        if use_tools and tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        # Newer models accept max_completion_tokens; older ones accept max_tokens.
        kwargs["max_completion_tokens"] = max_tokens
        try:
            resp = await client.chat.completions.create(**kwargs)
        except TypeError:
            kwargs.pop("max_completion_tokens", None)
            kwargs["max_tokens"] = max_tokens
            resp = await client.chat.completions.create(**kwargs)

        u = getattr(resp, "usage", None)
        total_in += getattr(u, "prompt_tokens", 0) or 0
        total_out += getattr(u, "completion_tokens", 0) or 0
        msg = resp.choices[0].message
        text = msg.content or ""
        if text and on_text:
            on_text(text)

        tool_calls = list(msg.tool_calls or [])
        assistant_msg = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_msg["tool_calls"] = [{
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            } for tc in tool_calls]
        messages.append(assistant_msg)

        if not use_tools or not tool_calls:
            return {"input_tokens": total_in, "output_tokens": total_out}

        for tc in tool_calls:
            name = tc.function.name
            args = _json_args(tc.function.arguments or "{}")
            if allow_delegate and name == "delegate":
                agent = args.get("agent", "")
                if on_tool:
                    on_tool(f"delegate→{agent}")
                t0 = time.perf_counter()
                out_text = await run_subagent(provider_client, agent, args.get("task", ""),
                                              on_tool=on_tool, model=model)
                if on_tool_result:
                    on_tool_result(ToolExecution(
                        f"delegate→{agent}", args, out_text, False,
                        int((time.perf_counter() - t0) * 1000),
                    ))
            else:
                if on_tool:
                    on_tool(name)
                result = await _execute_tool(name, args, by_name)
                out_text = result.text
                if on_tool_result:
                    on_tool_result(result)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out_text})


# ─────────────────────────────────────────────────────────────────────
# 子 agent 委派（≈ Claude Code 的 Task / AgentTool）
# ─────────────────────────────────────────────────────────────────────
def _subagent_toolset(agent) -> tuple[list[dict], dict]:
    """把子 agent 的工具白名单（mcp__fin__xxx 全名）解析成受限的 schema + 名表。"""
    allowed = {full.split("__")[-1] for full in (getattr(agent, "tools", None) or [])}
    tools = [t for t in ALL_TOOLS if t.name in allowed]
    return build_tool_schemas(tools), {t.name: t for t in tools}


def _last_assistant_text(messages: list[dict]) -> str:
    """取 messages 里最后一条 assistant 的纯文本。"""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            content = m.get("content")
            if isinstance(content, list):
                return "".join(b.get("text", "") for b in content
                               if isinstance(b, dict) and b.get("type") == "text").strip()
            if isinstance(content, str):
                return content.strip()
    return ""


async def run_subagent(client, name: str, task: str, on_tool=None,
                       model: str | None = None) -> str:
    """用受限工具集 + 子 agent 的 system 提示，独立跑一轮，返回它的结论文本。"""
    from agents import AGENTS  # 延迟导入避免与 agents→prompts→engine 的环

    agent = AGENTS.get(name)
    if agent is None:
        return (f"未知子 agent：{name}。可选："
                + "、".join(AGENTS.keys()))
    schema, by_name = _subagent_toolset(agent)
    messages: list[dict] = [{"role": "user", "content": str(task or "")}]
    await run_turn(
        client, agent.prompt, messages,
        on_text=None, on_tool=on_tool,
        model=model, tools_schema=schema, tool_by_name=by_name,
        allow_delegate=False, max_iters=8,
    )
    return _last_assistant_text(messages) or "（子 agent 无文本输出）"
