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
命令：/help · /portfolio 看持仓 · /memory · /sources · exit 退出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

HELP_TEXT = """可用命令（本地直接执行，不耗 token）：
  /help  /portfolio 看持仓  /memory  /sources  exit 退出

不知道怎么问？直接照着下面这些说就行：

【录入资产】
  · 我持有沪深300ETF 6万元、国债ETF 4万元、黄金ETF 2万元
  · 帮我把这笔加进组合：某科技基金 3万，行业科技
【看资产 / 诊断风险】
  · /portfolio                （看资产看板）
  · 我的组合有什么风险？        （单一持仓/行业/现金集中度诊断）
  · 我现在现金比例够吗？
【研究 / 解读】
  · 现在的紧缩预期对股和债分别什么影响？（检索知识库，带出处）
  · 沪深300现在贵不贵？          （PE/PB 历史分位）
  · 现在利率/CPI是什么水平？      （宏观数据）
【配置 / 复盘】
  · 用财富池的三脚架，帮我看看配置合不合理
  · 帮我做一套稳健型的资产配置"""


def opening_guidance() -> str:
    """按持仓状态给定制的开场引导——直接解决"不知道怎么问"。"""
    try:
        from tools.holdings import _load
        items = _load()
    except Exception:
        items = []
    if not items:
        return (
            "👋 还没录入持仓。照着下面任意一句开始就行：\n"
            "  · 我持有沪深300ETF 6万元、国债ETF 4万元\n"
            "  · 现在的紧缩预期对股债分别什么影响？\n"
            "录入后再问『我的组合有什么风险』。输入 /help 看更多问法。\n"
        )
    return (
        f"📂 已记住你的 {len(items)} 笔持仓。可以这样问：\n"
        "  · 我的组合有什么风险？     · /portfolio 看资产看板\n"
        "  · 沪深300现在贵不贵？      · 结合现在的宏观环境，我的配置合理吗？\n"
        "输入 /help 看更多问法。\n"
    )


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
    if cmd in ("/portfolio", "/p", "/holdings"):
        import json
        from tools.holdings import list_holdings
        r = await _handler(list_holdings)({})
        try:
            data = json.loads(r["content"][0]["text"])
            print(f"组合合计 {data['total']} 元，共 {data['count']} 笔：")
            for h in data["holdings"]:
                print(f"  #{h['id']} {h['name']}（{h['asset_class']}）{h['amount']} 元")
            print("  大类分布：" + "，".join(f"{k} {v}" for k, v in data["by_class"].items()))
        except Exception:
            print(r["content"][0]["text"])
        return True
    return False


async def main() -> None:
    print(BANNER)
    print(opening_guidance())

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
