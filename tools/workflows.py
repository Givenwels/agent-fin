"""Financial workflow contracts.

This module gives the model a structured task contract before it starts complex
financial work. It does not execute the workflow; it tells the agent which
steps, tools, checks, and guardrails must be visible before the final answer.
"""

from __future__ import annotations

import json

from .base import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None


WORKFLOW_TYPES = ["allocation", "rebalance", "decision", "review", "risk_check"]

_ALIASES = {
    "asset_allocation": "allocation",
    "allocate": "allocation",
    "配置": "allocation",
    "资产配置": "allocation",
    "调仓": "rebalance",
    "rebalance": "rebalance",
    "order_list": "rebalance",
    "买卖": "decision",
    "买入": "decision",
    "卖出": "decision",
    "decision_checklist": "decision",
    "复盘": "review",
    "review_report": "review",
    "risk": "risk_check",
    "风险": "risk_check",
    "风险体检": "risk_check",
}


_WORKFLOWS = {
    "allocation": {
        "title": "大类资产配置工作流",
        "plan_steps": [
            "确认或读取风险画像与投资目标",
            "检索配置框架或宏观背景并说明来源",
            "确定候选资产与角色分工",
            "获取候选资产行情数据",
            "运行配置优化或组合指标计算",
            "读取当前持仓并对比差异",
            "给出再平衡纪律与证伪条件",
            "执行最终任务检查后输出结论",
        ],
        "required_tools": [
            "start_financial_workflow",
            "write_plan",
            "recall_memories",
            "kb_search",
            "get_price_history",
            "optimize_portfolio",
            "calc_portfolio_metrics",
            "list_holdings",
            "final_task_check",
        ],
        "completion_checklist": [
            "risk_profile",
            "framework_or_macro",
            "price_data",
            "optimization_or_metrics",
            "holdings_comparison",
            "rebalance_discipline",
            "invalidation_conditions",
            "disclaimer",
        ],
        "guardrails": [
            "输出参考配置和权衡，不输出确定性买卖指令。",
            "数据失败或使用离线样本时必须说明。",
            "若持仓为空，说明无法做当前持仓对比。",
        ],
    },
    "rebalance": {
        "title": "手动调仓参考工作流",
        "plan_steps": [
            "读取当前持仓",
            "确认并归一化目标权重",
            "生成仅供手动执行的调仓清单",
            "诊断调仓后的结构性风险",
            "标记大额变化、集中度、现金或缺失资产问题",
            "强调不下单不连券商并等待用户自行确认",
            "执行最终任务检查后输出参考清单",
        ],
        "required_tools": [
            "start_financial_workflow",
            "write_plan",
            "list_holdings",
            "generate_order_list",
            "diagnose_risk",
            "final_task_check",
        ],
        "completion_checklist": [
            "holdings_read",
            "target_weights",
            "manual_order_list",
            "risk_flags",
            "manual_only_boundary",
            "user_confirmation_boundary",
        ],
        "guardrails": [
            "调仓清单只是手动参考，不代表交易指令。",
            "不连接券商、不下单、不触碰账户。",
            "大额或高集中变化必须提示用户再确认。",
        ],
    },
    "decision": {
        "title": "买卖决策清单工作流",
        "plan_steps": [
            "加载投资决策 checklist",
            "逐项询问标的逻辑与能力圈",
            "在需要时查询估值、持仓或风险",
            "要求用户写出三个证伪条件",
            "总结逻辑、风险点与仍未回答的问题",
            "用户作出决策后再建议记录投资日记",
            "执行最终任务检查后输出纪律化小结",
        ],
        "required_tools": [
            "start_financial_workflow",
            "write_plan",
            "decision_checklist",
            "get_valuation",
            "diagnose_risk",
            "add_journal",
            "final_task_check",
        ],
        "completion_checklist": [
            "checklist_loaded",
            "one_question_at_a_time",
            "valuation_or_risk_when_useful",
            "invalidation_conditions",
            "decision_summary",
            "journal_offer",
            "no_direct_order",
        ],
        "guardrails": [
            "逐项追问，不一次甩完整清单。",
            "不替用户拍板买卖。",
            "只有用户实际决定后才建议记录日记。",
        ],
    },
    "review": {
        "title": "周/月复盘工作流",
        "plan_steps": [
            "读取复盘汇总数据",
            "总结组合概览与快照变化",
            "解释结构性风险提示",
            "回看期间投资日记",
            "识别已兑现或证伪的旧逻辑",
            "给出下期关注点而非买卖指令",
            "执行最终任务检查后输出复盘报告",
        ],
        "required_tools": [
            "start_financial_workflow",
            "write_plan",
            "review_report",
            "list_journal",
            "diagnose_risk",
            "final_task_check",
        ],
        "completion_checklist": [
            "review_data",
            "board_summary",
            "risk_summary",
            "journal_review",
            "thesis_check",
            "next_watch_points",
            "disclaimer",
        ],
        "guardrails": [
            "复盘给观察点和纪律，不给下期买卖指令。",
            "历史逻辑没有记录时要说明无法验证。",
            "快照缺失时说明无法做环比。",
        ],
    },
    "risk_check": {
        "title": "组合风险体检工作流",
        "plan_steps": [
            "读取持仓或资产看板",
            "运行结构性风险诊断",
            "按严重程度解释风险",
            "给出方向级改善思路",
            "若用户需要具体权重则转入配置或调仓工作流",
            "执行最终任务检查后输出风险体检",
        ],
        "required_tools": [
            "start_financial_workflow",
            "write_plan",
            "list_holdings",
            "portfolio_dashboard",
            "diagnose_risk",
            "final_task_check",
        ],
        "completion_checklist": [
            "holdings_or_dashboard",
            "risk_diagnosis",
            "severity_explanation",
            "directional_improvements",
            "no_trade_instruction",
        ],
        "guardrails": [
            "风险体检只讲结构与方向，不直接给买卖命令。",
            "持仓为空时先引导录入。",
            "具体权重需求必须转入配置或调仓流程。",
        ],
    },
}


def resolve_workflow_type(workflow_type: str) -> str | None:
    key = str(workflow_type or "").strip()
    if key in _WORKFLOWS:
        return key
    low = key.lower().replace("-", "_").replace(" ", "_")
    if low in _WORKFLOWS:
        return low
    return _ALIASES.get(key) or _ALIASES.get(low)


def workflow_contract(workflow_type: str, context: str = "") -> dict:
    resolved = resolve_workflow_type(workflow_type)
    if resolved is None:
        return {
            "is_error": True,
            "message": f"未知 workflow_type：{workflow_type}。可选：{', '.join(WORKFLOW_TYPES)}",
        }

    spec = _WORKFLOWS[resolved]
    return {
        "workflow_type": resolved,
        "title": spec["title"],
        "context": str(context or "").strip(),
        "plan_tasks": [{"step": step, "status": "pending"} for step in spec["plan_steps"]],
        "required_tools": spec["required_tools"],
        "completion_checklist": spec["completion_checklist"],
        "guardrails": spec["guardrails"],
        "usage": (
            "先用 write_plan 写入 plan_tasks；每次只保留一个 in_progress；"
            "完成后调用 final_task_check，再输出最终结论。"
        ),
    }


@tool(
    "start_financial_workflow",
    "启动复杂金融任务的显式工作流。workflow_type 取 allocation/rebalance/decision/review/risk_check；"
    "返回计划步骤、建议工具、完成检查项和金融护栏。它不执行任务，只给 agent 一个必须遵守的任务合同。",
    {"workflow_type": str, "context": str},
    annotations=_RO,
    required=("workflow_type",),
)
async def start_financial_workflow(args: dict) -> dict:
    payload = workflow_contract(args.get("workflow_type", ""), args.get("context", ""))
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": bool(payload.get("is_error")),
    }
