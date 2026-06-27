"""Final task checks for complex financial workflows."""

from __future__ import annotations

import json

from claude_agent_sdk import tool

from .workflows import resolve_workflow_type, workflow_contract

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None


_LABELS = {
    "risk_profile": "确认或读取风险画像与投资目标",
    "framework_or_macro": "检索配置框架或宏观背景",
    "price_data": "获取候选资产行情数据",
    "optimization_or_metrics": "运行配置优化或组合指标计算",
    "holdings_comparison": "对比当前持仓",
    "rebalance_discipline": "给出再平衡纪律",
    "invalidation_conditions": "给出证伪条件",
    "disclaimer": "包含合规免责声明",
    "holdings_read": "读取当前持仓",
    "target_weights": "确认目标权重",
    "manual_order_list": "生成手动参考调仓清单",
    "risk_flags": "标记结构性风险",
    "manual_only_boundary": "说明手动执行和不下单边界",
    "user_confirmation_boundary": "提示用户自行确认",
    "checklist_loaded": "加载投资决策 checklist",
    "one_question_at_a_time": "逐项追问",
    "valuation_or_risk_when_useful": "必要时使用估值或风险工具",
    "decision_summary": "总结决策逻辑与风险",
    "journal_offer": "提供日记记录建议",
    "no_direct_order": "未输出直接买卖命令",
    "review_data": "读取复盘数据",
    "board_summary": "总结组合概览",
    "risk_summary": "总结风险提示",
    "journal_review": "回看投资日记",
    "thesis_check": "检查旧逻辑是否兑现或证伪",
    "next_watch_points": "给出下期关注点",
    "holdings_or_dashboard": "读取持仓或资产看板",
    "risk_diagnosis": "运行风险诊断",
    "severity_explanation": "按严重程度解释风险",
    "directional_improvements": "给出方向级改善思路",
    "no_trade_instruction": "未给出交易指令",
}


def _norm_list(values) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def _required_ids(workflow_type: str) -> list[str]:
    contract = workflow_contract(workflow_type)
    if contract.get("is_error"):
        return []
    return list(contract["completion_checklist"])


def run_final_check(workflow_type: str, completed_steps, used_tools, notes: str) -> dict:
    resolved = resolve_workflow_type(workflow_type)
    if resolved is None:
        return {
            "workflow_type": str(workflow_type or ""),
            "passed": False,
            "missing": [{"id": "workflow_type", "label": "有效 workflow_type"}],
            "warnings": [],
            "final_instruction": "未知 workflow_type，先调用 start_financial_workflow 获取有效工作流。",
        }

    completed = set(_norm_list(completed_steps))
    tools = set(_norm_list(used_tools))
    note_text = str(notes or "")
    required = _required_ids(resolved)
    missing = [{"id": rid, "label": _LABELS.get(rid, rid)} for rid in required if rid not in completed]

    warnings: list[str] = []
    if resolved == "rebalance":
        used_order = "generate_order_list" in tools or "manual_order_list" in completed
        has_manual_note = _contains_any(note_text, ["手动", "不下单", "不连券商", "manual", "no order"])
        if used_order and not has_manual_note:
            warnings.append("调仓清单必须说明只是手动参考，不下单、不连券商。")

    destructive_tools = {"remove_holding", "forget_memory"}
    if destructive_tools & tools and not _contains_any(note_text, ["确认", "用户确认", "已确认"]):
        warnings.append("删除持仓或记忆前应确认这是用户明确要求。")

    direct_trade_words = ["必须买", "必须卖", "立刻买", "立刻卖", "全仓", "梭哈"]
    if _contains_any(note_text, direct_trade_words):
        warnings.append("最终表述疑似包含确定性买卖指令，应改成风险收益权衡和用户自行决策。")

    passed = not missing and not warnings
    if passed:
        final_instruction = "检查通过。最终回答应简洁说明数据来源、关键假设、风险边界和下一步可选动作。"
    else:
        final_instruction = "检查未通过。先补齐 missing 项；无法补齐时，在最终回答中明确说明限制和未完成原因。"

    return {
        "workflow_type": resolved,
        "passed": passed,
        "missing": missing,
        "warnings": warnings,
        "final_instruction": final_instruction,
    }


@tool(
    "final_task_check",
    "复杂金融任务最终回答前的检查。workflow_type 取 allocation/rebalance/decision/review/risk_check；"
    "completed_steps 传已完成的检查项 id；used_tools 传本任务用过的工具名；notes 写假设、失败、边界说明。",
    {"workflow_type": str, "completed_steps": list, "used_tools": list, "notes": str},
    annotations=_RO,
)
async def final_task_check(args: dict) -> dict:
    payload = run_final_check(
        args.get("workflow_type", ""),
        args.get("completed_steps") or [],
        args.get("used_tools") or [],
        args.get("notes", ""),
    )
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
