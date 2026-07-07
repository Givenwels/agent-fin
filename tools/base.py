"""本地 @tool 装饰器——取代 claude_agent_sdk 的同名装饰器，彻底去掉对它的依赖。

`@tool(name, description, input_schema)` 包装一个 async handler，产出一个带
`.name / .description / .input_schema / .handler` 的对象，与原 `SdkMcpTool` 同构，
所以 engine.py（按这些属性构造 Anthropic tools 参数并调用 handler）无需任何改动。

input_schema 仍用简化形式 `{"参数名": python_type}`（python_type ∈ str/int/float/bool/list/dict），
由 engine.build_tool_schemas 转成 JSON Schema。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class ToolDef:
    """一个工具：名字、给模型看的描述、参数 schema、底层 async handler。"""
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Awaitable[dict]]
    annotations: Any = None


def tool(name: str, description: str, input_schema: dict, annotations: Any = None):
    """装饰一个 `async def fn(args: dict) -> dict` 的工具实现。

    handler 约定返回 {"content": [{"type": "text", "text": str}], "isError": bool?}（MCP 形态）。
    """
    def deco(fn: Callable[[dict], Awaitable[dict]]) -> ToolDef:
        return ToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=fn,
            annotations=annotations,
        )
    return deco
