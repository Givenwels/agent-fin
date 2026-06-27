"""金融工具集合。

对照源码：每个 @tool 函数 ≈ Claude Code 里的一个 Tool 对象
（restored-src/src/tools/ 下每个目录一个工具）。

三组工具：
  · 记忆(自进化)  save_memory / recall_memories / forget_memory   （≈ CLAUDE.md 机制）
  · 知识库导航    kb_index / kb_search / kb_read                  （≈ Glob / Grep / Read）
  · 量化计算      get_price_history / calc_portfolio_metrics / optimize_portfolio
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
from .memory import (
    save_memory,
    recall_memory,
    recall_memories,
    forget_memory,
    load_memory_block,
)
from .playbook import start_allocation, decision_checklist
from .portfolio import calc_portfolio_metrics, optimize_portfolio

# 暴露给 create_sdk_mcp_server 的工具清单
ALL_TOOLS = [
    start_allocation, decision_checklist,
    add_holding, list_holdings, update_holding, remove_holding, portfolio_dashboard,
    diagnose_risk,
    add_journal, list_journal, review_report,
    save_memory, recall_memory, recall_memories, forget_memory,
    kb_index, kb_search, kb_read,
    get_macro_indicator, get_valuation,
    get_price_history, calc_portfolio_metrics, optimize_portfolio,
]

__all__ = [
    "ALL_TOOLS",
    "start_allocation", "decision_checklist",
    "add_holding", "list_holdings", "update_holding", "remove_holding", "portfolio_dashboard",
    "diagnose_risk",
    "add_journal", "list_journal", "review_report",
    "save_memory", "recall_memory", "recall_memories", "forget_memory", "load_memory_block",
    "kb_index", "kb_search", "kb_read",
    "get_macro_indicator", "get_valuation",
    "get_price_history", "calc_portfolio_metrics", "optimize_portfolio",
    "SAMPLE_RETURNS",
]
