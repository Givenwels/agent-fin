"""Human-readable catalog for local agent tools."""

from __future__ import annotations

from typing import Iterable


GROUP_RULES = [
    ("工作流", {"start_financial_workflow", "final_task_check", "write_plan", "start_allocation", "decision_checklist"}),
    ("持仓", {"add_holding", "list_holdings", "update_holding", "remove_holding", "portfolio_dashboard"}),
    ("风险与调仓", {"diagnose_risk", "generate_order_list"}),
    ("日记复盘", {"add_journal", "list_journal", "review_report", "export_report", "push_notification"}),
    ("记忆", {"save_memory", "recall_memory", "recall_memories", "forget_memory"}),
    ("知识库", {"kb_index", "kb_search", "kb_read"}),
    ("数据", {"get_macro_indicator", "get_valuation", "get_news", "get_price_history"}),
    ("组合计算", {"calc_portfolio_metrics", "optimize_portfolio"}),
]


def tool_group(name: str) -> str:
    for group, names in GROUP_RULES:
        if name in names:
            return group
    return "其他"


def _schema_text(schema: dict) -> str:
    if not schema:
        return "-"
    parts = []
    for key, typ in schema.items():
        name = getattr(typ, "__name__", str(typ))
        parts.append(f"{key}:{name}")
    return ", ".join(parts)


def catalog_tools(tools: Iterable) -> list[dict]:
    rows = []
    for tool in tools:
        rows.append({
            "name": tool.name,
            "group": tool_group(tool.name),
            "schema": _schema_text(getattr(tool, "input_schema", None) or {}),
            "description": getattr(tool, "description", ""),
        })
    return sorted(rows, key=lambda r: (r["group"], r["name"]))


def render_tool_catalog(rows: list[dict], *, include_description: bool = False) -> str:
    if not rows:
        return "当前没有注册工具。"
    lines = ["工具目录："]
    current = None
    for row in rows:
        if row["group"] != current:
            current = row["group"]
            lines.append(f"\n【{current}】")
        line = f"- {row['name']}({row['schema']})"
        if include_description and row.get("description"):
            line += f"：{row['description']}"
        lines.append(line)
    return "\n".join(lines)
