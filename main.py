"""资产配置 Agent 入口。

═══════════════════════════════════════════════════════════════════════
对照源码：restored-src/src/query.ts（主对话循环）+ main.tsx（装配入口）
  装配三件套（和 TS 源码同构）：
    1. 工具      → create_sdk_mcp_server   （≈ tools.ts 注册工具表）
    2. 子 agent  → ClaudeAgentOptions.agents（≈ builtInAgents.ts）
    3. 系统提示  → ClaudeAgentOptions.system_prompt
  然后 ClaudeSDKClient 跑「输入→query→receive_response→打印」的循环
  （≈ query.ts：模型输出→执行 tool_use→把结果塞回→再问模型）。
═══════════════════════════════════════════════════════════════════════

运行：python main.py   （需先 conda activate finagent 且配置 ANTHROPIC_API_KEY）
"""

from __future__ import annotations

import asyncio
import sys

# Windows 控制台默认 GBK，强制 UTF-8 避免中文/特殊字符报错
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

# 自动加载 .env 里的 ANTHROPIC_API_KEY / FIN_KB_DIR 等（没有 .env 也不报错）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)

from agents import AGENTS, ALL_FIN_TOOLS
from prompts import MAIN_SYSTEM_PROMPT
from tools import ALL_TOOLS, load_memory_block


def build_options() -> ClaudeAgentOptions:
    # 1) 把金融工具打包成进程内 MCP server（名字 "fin" → 工具全名 mcp__fin__xxx）
    fin_server = create_sdk_mcp_server(name="fin", version="0.1.0", tools=ALL_TOOLS)

    # 2) 装配 agent 选项
    #    启动时把累积的记忆注入系统提示——这就是 L1 自进化的关键一步
    #    （≈ Claude Code 启动加载 CLAUDE.md）。每次开 agent，它都"记得"上次的你。
    system_prompt = MAIN_SYSTEM_PROMPT + load_memory_block()

    return ClaudeAgentOptions(
        mcp_servers={"fin": fin_server},
        allowed_tools=ALL_FIN_TOOLS,      # 预批准全部 fin 工具（只读，免权限弹窗）
        system_prompt=system_prompt,
        agents=AGENTS,                    # 注册 risk-profiler / allocator 子 agent
        permission_mode="acceptEdits",
        setting_sources=[],               # 空白起步：不加载用户全局 CLAUDE.md/设置
    )


async def stream_reply(client: ClaudeSDKClient) -> None:
    """打印一轮回复：文本块直接显示，工具调用给个提示。"""
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", flush=True)
                elif isinstance(block, ToolUseBlock):
                    name = block.name.replace("mcp__fin__", "")
                    print(f"\n  〔调用工具 {name}({block.input})〕", flush=True)
        elif isinstance(msg, ResultMessage):
            print()  # 一轮结束换行


BANNER = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  金融投研助手 · 专长大类资产配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
能力：宏观解读 / 组合分析 / 配置优化 / 一键资产配置 / 跨会话记忆
试试：
  · 现在的紧缩预期对股债分别什么影响？（检索知识库作答，带出处）
  · 分析 60% 沪深300ETF(510300) + 40% 国债ETF(511010) 的风险
  · 帮我做一套稳健型的资产配置
命令：/help 帮助 · /memory 看记忆 · /sources 看知识来源 · exit 退出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

HELP_TEXT = """可用命令（本地直接执行，不耗 token）：
  /help              显示本帮助
  /memory            查看 agent 当前记住的关于你的信息
  /sources           查看知识库收录了哪些来源/作者
  exit / quit / q    退出

直接打字就是和 agent 对话。它能：
  1) 宏观/概念解读（检索多来源知识库，注明出处）
  2) 组合风险分析（年化收益/波动/夏普/最大回撤/风险贡献）
  3) 配置优化（风险平价 / 均值方差）
  4) 一键资产配置（说"帮我做套资产配置"触发完整流程）
  5) 记住你的风险画像/持仓/偏好（跨会话）"""


def _handler(tool_obj):
    """取出 @tool 对象底层可调用的 handler（供本地命令直接调用，不走 LLM）。"""
    for a in ("handler", "_handler", "func", "fn", "callback"):
        h = getattr(tool_obj, a, None)
        if callable(h):
            return h
    return None


async def handle_local_command(user: str) -> bool:
    """处理 /help、/memory、/sources 等本地命令。返回 True 表示已处理、无需问 LLM。"""
    cmd = user.lower()
    if cmd in ("/help", "/h", "/?", "？"):
        print(HELP_TEXT)
        return True
    if cmd in ("/memory", "/mem", "/m"):
        from tools import load_memory_block
        print(load_memory_block().strip())
        return True
    if cmd in ("/sources", "/source", "/kb", "/s"):
        import json
        from tools.knowledge import kb_index
        r = await _handler(kb_index)({})
        try:
            data = json.loads(r["content"][0]["text"])
            print(f"知识库共 {data['source_count']} 个来源、{data['total']} 篇：")
            for s in data["sources"]:
                print(f"  · {s['source']}（{s['count']} 篇）")
        except Exception:
            print(r["content"][0]["text"])
        return True
    return False


async def main() -> None:
    print(BANNER)

    async with ClaudeSDKClient(options=build_options()) as client:
        while True:
            try:
                user = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见")
                break
            if not user:
                continue
            if user.lower() in ("exit", "quit", "q"):
                print("再见")
                break
            if user.startswith("/") or user in ("？",):
                if await handle_local_command(user):
                    continue

            try:
                await client.query(user)
                print("助手 > ", end="", flush=True)
                await stream_reply(client)
            except Exception as e:
                # 单次出错（如模型瞬时报错、网络抖动）不应崩掉整个会话
                print(f"\n[出错] {type(e).__name__}: {e}\n（可重试上一句，或换个问法）")


if __name__ == "__main__":
    asyncio.run(main())
