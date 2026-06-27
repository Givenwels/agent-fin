"""Workflow and final-check tests for agent-like financial task execution."""

from tools.workflows import WORKFLOW_TYPES, workflow_contract
from tools.checks import run_final_check


def test_workflow_contracts_cover_all_types():
    assert WORKFLOW_TYPES == ["allocation", "rebalance", "decision", "review", "risk_check"]

    for typ in WORKFLOW_TYPES:
        c = workflow_contract(typ, context="测试请求")
        assert c["workflow_type"] == typ
        assert c["context"] == "测试请求"
        assert len(c["plan_tasks"]) >= 4
        assert all(t["status"] == "pending" for t in c["plan_tasks"])
        assert c["required_tools"]
        assert c["completion_checklist"]
        assert c["guardrails"]


def test_workflow_contract_unknown_type():
    c = workflow_contract("not-a-workflow", context="")
    assert c["is_error"] is True
    assert "allocation" in c["message"]


def test_final_task_check_passes_complete_allocation():
    result = run_final_check(
        "allocation",
        completed_steps=[
            "risk_profile",
            "framework_or_macro",
            "price_data",
            "optimization_or_metrics",
            "holdings_comparison",
            "rebalance_discipline",
            "invalidation_conditions",
            "disclaimer",
        ],
        used_tools=["start_financial_workflow", "write_plan", "get_price_history", "optimize_portfolio"],
        notes="已说明不构成投资建议，若行情失败会说明数据来源。",
    )
    assert result["passed"] is True
    assert result["missing"] == []


def test_final_task_check_reports_missing_rebalance_items():
    result = run_final_check(
        "rebalance",
        completed_steps=["holdings_read", "target_weights"],
        used_tools=["generate_order_list"],
        notes="给出买卖金额。",
    )
    missing = {m["id"] for m in result["missing"]}
    assert "manual_order_list" in missing
    assert "risk_flags" in missing
    assert "manual_only_boundary" in missing
    assert result["passed"] is False
    assert any("手动参考" in w for w in result["warnings"])


def test_final_task_check_covers_every_workflow_type():
    cases = {
        "decision": [
            "checklist_loaded",
            "one_question_at_a_time",
            "valuation_or_risk_when_useful",
            "invalidation_conditions",
            "decision_summary",
            "journal_offer",
            "no_direct_order",
        ],
        "review": [
            "review_data",
            "board_summary",
            "risk_summary",
            "journal_review",
            "thesis_check",
            "next_watch_points",
            "disclaimer",
        ],
        "risk_check": [
            "holdings_or_dashboard",
            "risk_diagnosis",
            "severity_explanation",
            "directional_improvements",
            "no_trade_instruction",
        ],
    }
    for typ, steps in cases.items():
        result = run_final_check(typ, steps, used_tools=["final_task_check"], notes="不构成投资建议。")
        assert result["passed"] is True
        assert result["missing"] == []


def test_final_task_check_unknown_type():
    result = run_final_check("unknown", [], [], "")
    assert result["passed"] is False
    assert result["missing"]
    assert "未知" in result["final_instruction"]


def test_workflow_tools_registered_and_allowed():
    from tools import ALL_TOOLS
    from agents import ALL_FIN_TOOLS

    names = {getattr(t, "name", "") for t in ALL_TOOLS}
    assert "start_financial_workflow" in names
    assert "final_task_check" in names
    assert "mcp__fin__start_financial_workflow" in ALL_FIN_TOOLS
    assert "mcp__fin__final_task_check" in ALL_FIN_TOOLS

    missing = [tool for tool in ALL_FIN_TOOLS if tool.removeprefix("mcp__fin__") not in names]
    assert missing == []
