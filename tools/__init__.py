"""金融工具集合。

对照源码：每个 @tool 函数 ≈ Claude Code 里的一个 Tool 对象
（restored-src/src/tools/ 下每个目录一个工具）。

工具组：
  · 金融工作流与显式计划  start_financial_workflow / final_task_check / write_plan
  · 持仓、风险、调仓、日记、复盘
  · 记忆、知识库、宏观估值、行情、组合计算
"""

from .holdings import (
    add_holding,
    list_holdings,
    update_holding,
    remove_holding,
    portfolio_dashboard,
)
from .journal import add_journal, list_journal
from .knowledge import kb_index, kb_search, kb_read
from .macro import get_macro_indicator, get_valuation
from .market import get_price_history, SAMPLE_RETURNS
from .review import review_report
from .risk import diagnose_risk
from .orders import generate_order_list
from .memory import (
    save_memory,
    recall_memory,
    recall_memories,
    forget_memory,
    load_memory_block,
)
from .planner import write_plan
from .workflows import start_financial_workflow
from .checks import final_task_check
from .playbook import start_allocation, decision_checklist
from .portfolio import calc_portfolio_metrics, optimize_portfolio

# 暴露给 create_sdk_mcp_server 的工具清单
ALL_TOOLS = [
    start_financial_workflow, final_task_check,
    start_allocation, decision_checklist, write_plan,
    add_holding, list_holdings, update_holding, remove_holding, portfolio_dashboard,
    diagnose_risk, generate_order_list,
    add_journal, list_journal, review_report,
    save_memory, recall_memory, recall_memories, forget_memory,
    kb_index, kb_search, kb_read,
    get_macro_indicator, get_valuation,
    get_price_history, calc_portfolio_metrics, optimize_portfolio,
]

__all__ = [
    "ALL_TOOLS",
    "start_financial_workflow", "final_task_check",
    "start_allocation", "decision_checklist", "write_plan",
    "add_holding", "list_holdings", "update_holding", "remove_holding", "portfolio_dashboard",
    "diagnose_risk", "generate_order_list",
    "add_journal", "list_journal", "review_report",
    "save_memory", "recall_memory", "recall_memories", "forget_memory", "load_memory_block",
    "kb_index", "kb_search", "kb_read",
    "get_macro_indicator", "get_valuation",
    "get_price_history", "calc_portfolio_metrics", "optimize_portfolio",
    "SAMPLE_RETURNS",
]
