"""Capability and readiness reporting for the financial agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import api_config
import context_manager
import tool_catalog


ROOT = Path(__file__).resolve().parent

CORE_CAPABILITIES = [
    {
        "id": "agent_loop",
        "name": "自主 Agent 循环",
        "detail": "像 Claude Code 一样自己驱动 model -> tool_use -> tool_result -> final answer。",
    },
    {
        "id": "tool_use",
        "name": "本地工具调用",
        "detail": "把金融工具暴露成结构化 schema，支持必填/选填参数、超时、截断和轨迹记录。",
    },
    {
        "id": "context",
        "name": "上下文管理",
        "detail": "长会话会压缩成历史摘要，保留当前问题和最近关键回合。",
    },
    {
        "id": "memory",
        "name": "跨会话记忆",
        "detail": "记住风险画像、偏好、持仓和重要决策；当前问题只注入相关记忆。",
    },
    {
        "id": "planning",
        "name": "计划与任务自检",
        "detail": "复杂任务先写计划，结束前用 final_task_check 检查数据、风险和免责边界。",
    },
    {
        "id": "subagents",
        "name": "领域子 Agent",
        "detail": "可委派 macro-analyst、risk-profiler、allocator 做受限范围内的独立分析。",
    },
    {
        "id": "finance",
        "name": "金融投研工作流",
        "detail": "覆盖知识库检索、宏观/估值、组合计算、风险诊断、调仓清单、日记和复盘。",
    },
    {
        "id": "safety",
        "name": "金融安全边界",
        "detail": "NO_AUTO_ORDER：不连券商、不自动下单、不承诺收益；高风险删除工具需要确认。",
    },
]


def _is_high_risk_tool(tool) -> bool:
    if getattr(tool, "risk", "low") == "high":
        return True
    ann = getattr(tool, "annotations", None)
    return bool(getattr(ann, "destructiveHint", False))


def _tool_names(tools: Iterable) -> list[str]:
    return [str(getattr(tool, "name", "")) for tool in tools if getattr(tool, "name", "")]


def _group_counts(tools: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in tool_catalog.catalog_tools(tools):
        counts[row["group"]] = counts.get(row["group"], 0) + 1
    return counts


def _context_info(messages: list[dict] | None, stats: dict | None) -> dict:
    c = context_manager.context_stats(messages or [])
    stats = stats or {}
    return {
        "messages": c["messages"],
        "chars": c["chars"],
        "compactions": int(stats.get("context_compactions", 0) or 0),
        "tool_errors": int(stats.get("tool_errors", 0) or 0),
        "turns": int(stats.get("turns", 0) or 0),
        "tokens": int(stats.get("tokens", 0) or 0),
    }


def build_agent_profile(
    *,
    tools: Iterable,
    env: dict | None = None,
    messages: list[dict] | None = None,
    stats: dict | None = None,
) -> dict:
    tools = list(tools)
    high_risk = [tool for tool in tools if _is_high_risk_tool(tool)]
    return {
        "title": "Fin Agent 能力画像",
        "positioning": "Claude Code-like personal financial research agent",
        "api": api_config.current_api_status(env or os.environ),
        "tool_count": len(tools),
        "tool_groups": _group_counts(tools),
        "high_risk_tool_count": len(high_risk),
        "high_risk_tools": _tool_names(high_risk),
        "capabilities": list(CORE_CAPABILITIES),
        "context": _context_info(messages, stats),
        "limits": [
            "NO_AUTO_ORDER：不连接券商、不自动下单、不替用户转账。",
            "NO_RETURN_PROMISE：不承诺收益，不输出确定性买卖指令。",
            "HUMAN_IN_THE_LOOP：删除记忆/持仓等高风险动作需要用户确认。",
            "DATA_SOURCE_AWARE：知识库观点和实时数据要说明来源、时间和假设。",
        ],
    }


def render_agent_profile(profile: dict) -> str:
    api = profile["api"]
    ctx = profile["context"]
    groups = "；".join(f"{name}:{count}" for name, count in profile["tool_groups"].items())
    lines = [
        "Fin Agent 能力画像",
        "",
        f"定位：{profile['positioning']}",
        "目标：保留 Claude Code 的 agent loop、工具调用、上下文、记忆和自检感，但只服务你的金融投研/配置/复盘。",
        "",
        "Claude Code-like 能力映射：",
    ]
    for item in profile["capabilities"]:
        lines.append(f"- {item['name']}：{item['detail']}")
    lines.extend([
        "",
        "本机状态：",
        f"- API：provider={api['provider']} model={api['model']} configured={api['configured']} key={api['key']}",
        f"- 工具：{profile['tool_count']} 个；高风险 {profile['high_risk_tool_count']} 个 "
        f"({', '.join(profile['high_risk_tools']) or '无'})",
        f"- 分组：{groups or '无'}",
        f"- 上下文：{ctx['messages']} 条，约 {ctx['chars']} 字符，压缩 {ctx['compactions']} 次，"
        f"本会话 {ctx['turns']} 轮/{ctx['tokens']} token",
        "",
        "硬边界：",
    ])
    for limit in profile["limits"]:
        lines.append(f"- {limit}")
    return "\n".join(lines)


def _check(check_id: str, status: str, name: str, detail: str, fix: str = "") -> dict:
    return {"id": check_id, "status": status, "name": name, "detail": detail, "fix": fix}


def build_agent_doctor(
    *,
    tools: Iterable,
    env: dict | None = None,
    root: Path | str | None = None,
    stats: dict | None = None,
) -> dict:
    env = env or os.environ
    root = Path(root or ROOT)
    tools = list(tools)
    api = api_config.current_api_status(env)
    checks = []
    if api["configured"]:
        checks.append(_check("api", "OK", "API 配置", f"{api['provider']} / {api['model']} / key={api['key']}"))
    else:
        checks.append(_check(
            "api",
            "WARN",
            "API 配置",
            "未发现 OPENAI_API_KEY/CODEX_API_KEY 或 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN。",
            "运行 fin setup，或复用 Claude Code/DeepSeek 环境后运行 fin test。",
        ))

    high_risk_names = _tool_names([t for t in tools if _is_high_risk_tool(t)])
    high_risk_text = ", ".join(high_risk_names) if high_risk_names else "无"
    checks.append(_check(
        "tools",
        "OK" if tools else "FAIL",
        "工具注册",
        f"已注册 {len(tools)} 个工具；高风险 {high_risk_text}。",
        "如果为 0，检查 tools/__init__.py 的 ALL_TOOLS。",
    ))
    for dirname in ("memory", "portfolio", "playbooks"):
        path = root / dirname
        checks.append(_check(
            f"dir:{dirname}",
            "OK" if path.exists() else "WARN",
            f"{dirname}/ 目录",
            "存在" if path.exists() else "不存在；首次运行相关功能时可能自动创建。",
        ))
    checks.append(_check(
        "launcher",
        "OK" if (root / "fin.cmd").exists() else "WARN",
        "fin 启动器",
        "项目内 fin.cmd 存在" if (root / "fin.cmd").exists() else "项目内未发现 fin.cmd。",
        "如命令行不能直接输入 fin，重新运行 setup.bat 或 npm 全局链接。",
    ))
    ctx = _context_info([], stats)
    checks.append(_check(
        "session",
        "OK",
        "本会话统计",
        f"{ctx['turns']} 轮 / {ctx['tokens']} token / 工具错误 {ctx['tool_errors']} 次。",
    ))
    return {
        "title": "Fin Agent 运行体检",
        "network": "not called",
        "api": api,
        "checks": checks,
    }


def render_agent_doctor(report: dict) -> str:
    lines = [f"{report['title']} (network: {report['network']})", ""]
    for check in report["checks"]:
        line = f"[{check['status']}] {check['name']}：{check['detail']}"
        if check.get("fix") and check["status"] != "OK":
            line += f"\n    建议：{check['fix']}"
        lines.append(line)
    return "\n".join(lines)
