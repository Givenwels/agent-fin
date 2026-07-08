"""资产配置 Agent 入口。

═══════════════════════════════════════════════════════════════════════
本项目是一个「真独立」Agent：核心对话循环在 engine.py（对照 Claude Code 的
query.ts），默认用 OpenAI SDK 接 Codex/OpenAI API，自己驱动
    输入 → 模型 → 执行 tool_use → 回填 tool_result → 再问模型 → 最终回答。
不再经由 claude-agent-sdk 拉起 `claude` 子进程。装配三件套：
    1. 工具      → tools.ALL_TOOLS（engine 内部转成 Anthropic tools 参数）
    2. 系统提示  → prompts.MAIN_SYSTEM_PROMPT + 累积记忆
    3. 上下文    → context_manager 压缩历史 + memory 按需取相关记忆
    4. 对话循环  → engine.run_turn
═══════════════════════════════════════════════════════════════════════

运行：python main.py   （需先 conda activate finagent 且配置端点/密钥环境变量）
续接上次对话：python main.py -c
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time

import context_manager
import tool_catalog
import trace_state

# Windows 控制台默认 GBK：① 把控制台代码页切到 UTF-8(65001) ② Python 输出也用 UTF-8。
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

# 自动加载 .env 里的密钥/端点等（没有 .env 也不报错）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import engine
import api_config
from prompts import MAIN_SYSTEM_PROMPT
from tools import load_memory_block
from tools import ALL_TOOLS
from tools.memory import load_relevant_memory_block

SESSION_FILE = pathlib.Path(__file__).resolve().parent / "portfolio" / "session.json"


def save_session(messages: list[dict]) -> None:
    """退出时把对话历史存盘，供下次 -c 续接。"""
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_session() -> list[dict]:
    if not SESSION_FILE.exists():
        return []
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def ask(client, system: str, messages: list[dict], stats: dict) -> None:
    """跑一个用户回合：打印回复 + 末尾一行可观测性 footer（工具/用时/token）。"""
    tools_used: list[str] = []
    tool_events: list[engine.ToolExecution] = []
    t0 = time.time()

    compact = context_manager.compact_messages(messages)
    if compact.changed:
        stats["context_compactions"] = stats.get("context_compactions", 0) + 1

    def on_text(txt: str) -> None:
        print(txt, end="", flush=True)

    def on_tool(name: str) -> None:
        tools_used.append(name)
        print(f"\n  〔调用 {name}〕", flush=True)

    def on_tool_result(event: engine.ToolExecution) -> None:
        tool_events.append(event)
        trace = stats.get("trace")
        if trace:
            trace.record(event)

    current_user = ""
    if messages and messages[-1].get("role") == "user":
        current_user = str(messages[-1].get("content") or "")
    turn_system = system + load_relevant_memory_block(current_user)

    usage = await engine.run_turn(client, turn_system, messages, on_text, on_tool,
                                  on_tool_result=on_tool_result,
                                  allow_delegate=True)
    dur = time.time() - t0
    tok = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    stats["turns"] += 1
    stats["tokens"] += tok
    errors = sum(1 for e in tool_events if e.is_error)
    truncated = sum(1 for e in tool_events if e.truncated)
    stats["tool_errors"] = stats.get("tool_errors", 0) + errors
    tl = "、".join(dict.fromkeys(tools_used)) or "无"
    extra = []
    if errors:
        extra.append(f"工具错误:{errors}")
    if truncated:
        extra.append(f"截断:{truncated}")
    if compact.changed:
        extra.append(f"上下文压缩:{compact.summarized_messages}条")
    more = (" · " + " · ".join(extra)) if extra else ""
    print(f"\n  〔本轮 工具:{tl} · {dur:.1f}s · {tok} token{more}〕")


BANNER = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  金融投研助手 · 专长大类资产配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
能力：宏观解读 / 组合分析 / 配置优化 / 一键资产配置 / 跨会话记忆
试试：
  · 现在的紧缩预期对股债分别什么影响？（检索知识库作答，带出处）
  · 分析 60% 沪深300ETF(510300) + 40% 国债ETF(511010) 的风险
  · 帮我做一套稳健型的资产配置
命令：/help · /api · /tools · /trace · /context · /portfolio · /journal · /memory · /sources · /cost · exit 退出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

HELP_TEXT = """可用命令（本地直接执行，不耗 token）：
  /help  /api 看接口状态  /tools 看工具目录  /trace 看工具轨迹  /context 看上下文状态
  /portfolio 看持仓  /plan 看任务计划  /journal 看日记  /memory  /sources
  /cost 看本次会话用量  ·  exit 退出（退出时自动整理记忆）
默认新会话，打开直接问。想接上次对话历史：启动时加 -c（run.bat -c 或 python main.py -c）。
首次接入 Codex/OpenAI API：python main.py --setup-api；测试接口：python main.py --test-api。

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
        print(f"本次会话：{stats['turns']} 轮 · {stats['tokens']} token"
              "（第三方端点 $ 花费按 Claude 计价不准，请用 token × 你端点单价折算）")
        return True
    if cmd in ("/api", "/provider", "/model"):
        print(api_config.render_api_status())
        return True
    if cmd in ("/tools", "/tool"):
        rows = tool_catalog.catalog_tools(ALL_TOOLS)
        print(tool_catalog.render_tool_catalog(rows, include_description=False))
        return True
    if cmd in ("/tools full", "/tool full"):
        rows = tool_catalog.catalog_tools(ALL_TOOLS)
        print(tool_catalog.render_tool_catalog(rows, include_description=True))
        return True
    if cmd in ("/trace", "/traces"):
        trace = stats.get("trace")
        print(trace.render() if trace else "本次会话还没有工具调用。")
        return True
    if cmd in ("/context", "/ctx"):
        c = context_manager.context_stats(stats.get("messages", []))
        print(
            f"上下文：{c['messages']} 条 · 约 {c['chars']} 字符 · "
            f"本次压缩 {stats.get('context_compactions', 0)} 次 · "
            f"工具错误 {stats.get('tool_errors', 0)} 次"
        )
        return True
    if cmd in ("/memory", "/mem", "/m"):
        print(load_memory_block().strip())
        return True
    if cmd in ("/sources", "/source", "/kb", "/s"):
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
    if cmd in ("/plan", "/todo", "/tasks"):
        from tools.planner import load_plan, render
        print(render(load_plan()))
        return True
    if cmd in ("/journal", "/j", "/diary"):
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


async def auto_extract_memory(client, system: str, messages: list[dict]) -> None:
    """会话结束时让 agent 自动提炼并存储记忆（best-effort，失败不影响退出）。"""
    print("📝 正在整理本次对话的记忆…", flush=True)
    saved = 0

    def on_tool(name: str) -> None:
        nonlocal saved
        if name == "save_memory":
            saved += 1

    try:
        messages.append({"role": "user", "content": EXIT_EXTRACT_PROMPT})
        await engine.run_turn(client, system, messages, on_text=None, on_tool=on_tool)
        print(f"✓ 记忆已整理（更新 {saved} 条），下次打开我会记得。")
    except Exception as e:
        print(f"（记忆整理跳过：{type(e).__name__}）")


async def repl(continue_last: bool, stats: dict) -> None:
    """一个会话的 REPL 循环。continue_last=True 时载回上次对话历史。"""
    # 系统提示 = 主提示 + 累积记忆（≈ Claude Code 启动加载 CLAUDE.md），每次开启都"记得"你
    system = MAIN_SYSTEM_PROMPT + load_memory_block()
    client = engine.build_client()
    messages: list[dict] = load_session() if continue_last else []
    stats["messages"] = messages
    if continue_last and messages:
        print(f"（已接上上次对话，{len(messages)} 条历史）")

    try:
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
                    await auto_extract_memory(client, system, messages)
                save_session(messages)
                print("再见")
                break
            if user.startswith("/") or user in ("？",):
                if await handle_local_command(user, stats):
                    continue

            mark = len(messages)
            messages.append({"role": "user", "content": user})
            print("助手 > ", end="", flush=True)
            try:
                await ask(client, system, messages, stats)
            except Exception as e:
                # 单次出错（网络抖动/模型瞬时报错）不该污染上下文：回滚本回合追加的消息
                del messages[mark:]
                print(f"\n[出错] {type(e).__name__}: {e}\n（可重试上一句，或换个问法）")
    finally:
        close = getattr(client, "close", None)
        if close:
            try:
                await close()
            except Exception:
                pass


async def main() -> None:
    if any(a == "--setup-api" for a in sys.argv[1:]):
        api_config.setup_codex_api_interactive()
        return
    if any(a == "--test-api" for a in sys.argv[1:]):
        raise SystemExit(api_config.run_test_api_sync())

    print(BANNER)
    alert = pending_alert()
    if alert:
        print(alert)
    print(opening_guidance())

    if not api_config.current_api_status()["configured"]:
        print("API 未配置。请先运行：python main.py --setup-api")
        print("当前状态：")
        print(api_config.render_api_status())
        return

    # 续接做成可选、不打断：默认新会话。想接上次对话历史，启动时加 -c。
    resume = any(a in ("-c", "--continue") for a in sys.argv[1:])

    stats = {
        "turns": 0,
        "tokens": 0,
        "context_compactions": 0,
        "tool_errors": 0,
        "trace": trace_state.AgentTrace(),
    }
    await repl(resume, stats)


if __name__ == "__main__":
    asyncio.run(main())
