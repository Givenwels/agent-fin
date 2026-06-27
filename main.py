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
import os
import pathlib
import sys

# Windows 控制台默认 GBK：① 把控制台代码页切到 UTF-8(65001) ② Python 输出也用 UTF-8。
# 两者配合，无论用 run.bat 还是直接 python main.py，中文都不乱码。
try:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
except Exception:
    pass
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


def build_options(continue_last: bool = False) -> ClaudeAgentOptions:
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
        continue_conversation=continue_last,  # 会话续接：接上本目录最近一次对话
    )


def _tokens(usage) -> int:
    """从 usage(dict) 估算本轮总 token。"""
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)


def _cost_meaningful() -> bool:
    """SDK 的 total_cost_usd 按 Claude 美元价算。接 DeepSeek 等第三方端点时该值无意义，
    只显示 token（token 才是真实计费依据，用户按自己端点单价折算）。"""
    model = os.environ.get("ANTHROPIC_MODEL", "").lower()
    base = os.environ.get("ANTHROPIC_BASE_URL", "").lower()
    if "deepseek" in model or "deepseek" in base:
        return False
    if model and "claude" not in model and "anthropic" not in model:
        return False
    return True


async def stream_reply(client: ClaudeSDKClient, stats: dict) -> None:
    """打印一轮回复 + 末尾给一行可观测性footer（调了哪些工具/用时/token/累计花费）。"""
    tools_used = []
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", flush=True)
                elif isinstance(block, ToolUseBlock):
                    name = block.name.replace("mcp__fin__", "")
                    tools_used.append(name)
                    print(f"\n  〔调用 {name}〕", flush=True)
        elif isinstance(msg, ResultMessage):
            # 累计会话统计
            tok = _tokens(msg.usage)
            cost = float(msg.total_cost_usd or 0)
            stats["turns"] += 1
            stats["tokens"] += tok
            stats["cost"] += cost
            dur = (msg.duration_ms or 0) / 1000
            tl = "、".join(dict.fromkeys(tools_used)) or "无"
            cost_part = (f" · 累计 ${stats['cost']:.4f}"
                         if stats["cost"] and _cost_meaningful() else "")
            print(f"\n  〔本轮 工具:{tl} · {dur:.1f}s · {tok} token{cost_part}〕")


BANNER = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  金融投研助手 · 专长大类资产配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
能力：宏观解读 / 组合分析 / 配置优化 / 一键资产配置 / 跨会话记忆
试试：
  · 现在的紧缩预期对股债分别什么影响？（检索知识库作答，带出处）
  · 分析 60% 沪深300ETF(510300) + 40% 国债ETF(511010) 的风险
  · 帮我做一套稳健型的资产配置
命令：/help · /portfolio · /journal · /memory · /sources · /cost · exit 退出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

HELP_TEXT = """可用命令（本地直接执行，不耗 token）：
  /help  /portfolio 看持仓  /journal 看日记  /memory  /sources
  /cost 看本次会话用量  ·  exit 退出（退出时自动整理记忆）
默认新会话，打开直接问。想接上次对话历史：启动时加 -c（run.bat -c 或 python main.py -c）。

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


def pending_alert() -> str:
    """启动时若有定时监控(watch.py)留下的告警，主动提示——把"被动"变"主动"。"""
    f = pathlib.Path(__file__).resolve().parent / "portfolio" / "alerts" / "latest.md"
    if not f.exists():
        return ""
    try:
        body = f.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return ("⚠️ 上次定时监控发现风险（问我『详细说说风险』了解）：\n"
            + "\n".join("   " + ln for ln in body.splitlines()[:8]) + "\n")


def _handler(tool_obj):
    """取出 @tool 对象底层可调用的 handler（供本地命令直接调用，不走 LLM）。"""
    for a in ("handler", "_handler", "func", "fn", "callback"):
        h = getattr(tool_obj, a, None)
        if callable(h):
            return h
    return None


async def handle_local_command(user: str, stats: dict) -> bool:
    """处理 /help、/memory、/sources、/cost 等本地命令。返回 True 表示已处理、无需问 LLM。"""
    cmd = user.lower()
    if cmd in ("/help", "/h", "/?", "？"):
        print(HELP_TEXT)
        return True
    if cmd in ("/cost", "/stats", "/usage"):
        line = f"本次会话：{stats['turns']} 轮 · {stats['tokens']} token"
        if _cost_meaningful() and stats["cost"]:
            line += f" · 约 ${stats['cost']:.4f}"
        else:
            line += "（你接的是 DeepSeek 等第三方端点，$ 花费按 Claude 计价不准；"
            line += "请用 token × 你端点的单价折算人民币）"
        print(line)
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
    if cmd in ("/journal", "/j", "/diary"):
        import json
        from tools.journal import list_journal
        r = await _handler(list_journal)({})
        try:
            data = json.loads(r["content"][0]["text"])
            print(f"投资日记共 {data['count']} 条，显示最近 {data['showing']} 条：")
            for e in data["entries"]:
                print(f"  #{e['id']} {e['date']} [{e['type']}] {e['title'] or e['content'][:30]}")
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


EXIT_EXTRACT_PROMPT = (
    "【会话结束·记忆整理】回顾本次对话，把值得长期记住的、关于用户的稳定事实用 save_memory 存下来"
    "（风险画像/持仓偏好/重要决策/明确偏好；只存跨会话有用的，不存一次性闲聊）。"
    "再用 save_memory（category=会话, key=上次小结）存一句话概括本次聊了什么。完成后只回复'记忆已整理'。"
)


async def auto_extract_memory(client: ClaudeSDKClient) -> None:
    """会话结束时让 agent 自动提炼并存储记忆（best-effort，失败不影响退出）。"""
    print("📝 正在整理本次对话的记忆…", flush=True)
    try:
        await client.query(EXIT_EXTRACT_PROMPT)
        saved = 0
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, ToolUseBlock) and b.name.endswith("save_memory"):
                        saved += 1
            elif isinstance(msg, ResultMessage):
                break
        print(f"✓ 记忆已整理（更新 {saved} 条），下次打开我会记得。")
    except Exception as e:
        print(f"（记忆整理跳过：{type(e).__name__}）")


async def repl(continue_last: bool, stats: dict) -> None:
    """一个会话的 REPL 循环。continue_last=True 时接上次对话历史。"""
    async with ClaudeSDKClient(options=build_options(continue_last=continue_last)) as client:
        if continue_last:
            print("（已接上上次对话）")
        while True:
            try:
                user = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见")
                break
            if not user:
                continue
            if user.lower() in ("exit", "quit", "q"):
                if stats["turns"] > 0:
                    await auto_extract_memory(client)
                print("再见")
                break
            if user.startswith("/") or user in ("？",):
                if await handle_local_command(user, stats):
                    continue

            try:
                await client.query(user)
                print("助手 > ", end="", flush=True)
                await stream_reply(client, stats)
            except Exception as e:
                # 单次出错（如模型瞬时报错、网络抖动）不应崩掉整个会话
                print(f"\n[出错] {type(e).__name__}: {e}\n（可重试上一句，或换个问法）")


async def main() -> None:
    print(BANNER)
    alert = pending_alert()
    if alert:
        print(alert)
    print(opening_guidance())

    # 续接做成可选、不打断：默认新会话，打开直接开问。
    # 想接上次对话历史，启动时加 -c（python main.py -c，或 run.bat -c）。
    resume = any(a in ("-c", "--continue") for a in sys.argv[1:])

    stats = {"turns": 0, "tokens": 0, "cost": 0.0}
    try:
        await repl(resume, stats)
    except Exception as e:
        if resume:
            print(f"（接续上次失败：{type(e).__name__}，改为新会话）")
            await repl(False, stats)
        else:
            raise


if __name__ == "__main__":
    asyncio.run(main())
