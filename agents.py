"""子 Agent（领域专家）定义。

═══════════════════════════════════════════════════════════════════════
对照源码：restored-src/src/tools/AgentTool/built-in/exploreAgent.ts
  一个子 agent = description(何时用) + prompt(system) + tools(允许的工具子集) + model。
  主 agent 会在合适时机把任务"委派"给子 agent（源码里通过 AgentTool/Task 机制）。
  这正是你做"宏观研究员""配置专家"分工的标准范式。
═══════════════════════════════════════════════════════════════════════
"""

from claude_agent_sdk import AgentDefinition

from prompts import DISCLAIMER

# fin MCP server 暴露的工具全名：mcp__<server>__<tool>
WORKFLOW_TOOLS = [
    "mcp__fin__start_allocation",
]
HOLDINGS_TOOLS = [
    "mcp__fin__add_holding",
    "mcp__fin__list_holdings",
    "mcp__fin__update_holding",
    "mcp__fin__remove_holding",
    "mcp__fin__portfolio_dashboard",
]
MEMORY_TOOLS = [
    "mcp__fin__save_memory",
    "mcp__fin__recall_memories",
    "mcp__fin__forget_memory",
]
KB_TOOLS = [
    "mcp__fin__kb_index",
    "mcp__fin__kb_search",
    "mcp__fin__kb_read",
]
DATA_TOOLS = [
    "mcp__fin__get_macro_indicator",
    "mcp__fin__get_valuation",
]
QUANT_TOOLS = [
    "mcp__fin__get_price_history",
    "mcp__fin__calc_portfolio_metrics",
    "mcp__fin__optimize_portfolio",
]
ALL_FIN_TOOLS = (
    WORKFLOW_TOOLS + HOLDINGS_TOOLS + MEMORY_TOOLS + KB_TOOLS + DATA_TOOLS + QUANT_TOOLS
)

AGENTS = {
    # 宏观研究员：只读知识库，回答"现在是什么宏观环境/该用什么框架"
    "macro-analyst": AgentDefinition(
        description="判断当前宏观环境（利率/货币周期/紧缩预期/资产荒），用知识库框架给出大类倾向。",
        prompt=(
            "你是宏观研究员，依托多来源财经知识库（默认框架来自汤山老王，也兼采其他作者）。"
            "回答宏观/利率/货币/概念问题前，先 kb_search 检索、kb_read 读原文，再据此分析。"
            "产出：当前处于逻辑链哪一环、对股/债/商品/海外各大类的倾向、对应情景与信号。"
            "引用观点必须注明出处（哪位作者/来源），多来源有分歧时并陈；实时数据/点位提示另行核验。"
            "可用 get_macro_indicator 取利率/CPI/PMI/M2、get_valuation 取指数估值分位，让判断有真数据支撑。"
            "\n\n" + DISCLAIMER
        ),
        tools=KB_TOOLS + DATA_TOOLS,
        model="inherit",
    ),
    # 风险测评专家：纯对话，不需要工具
    "risk-profiler": AgentDefinition(
        description="评估用户风险承受能力与投资目标，输出风险等级与建议的股债比例区间。",
        prompt=(
            "你是风险测评专家。通过提问了解用户的：投资期限、可承受最大回撤、收入稳定性、"
            "投资经验、目标（养老/购房/增值）。综合给出风险等级（保守/稳健/平衡/积极/进取）"
            "和建议的权益比例区间，并解释依据。不要直接给具体标的。"
            "得到结论后，用 save_memory 把用户的风险等级、目标、关键约束记下来，方便以后想起。"
            "\n\n" + DISCLAIMER
        ),
        tools=MEMORY_TOOLS,
        model="inherit",
    ),
    # 配置专家：知识库 + 量化工具，生成并解释具体组合
    "allocator": AgentDefinition(
        description="在给定风险等级/宏观判断下，用数据和优化工具生成具体大类配置方案并解读。",
        prompt=(
            "你是大类资产配置专家。先用 kb 工具确认配置框架（矛/盾四层、再平衡纪律），"
            "再调用 get_price_history 取数据，用 optimize_portfolio（risk_parity 或 "
            "mean_variance）求权重，用 calc_portfolio_metrics 复核，输出权重、"
            "年化收益/波动/夏普/最大回撤、风险贡献，并解释为什么这样配、给出再平衡区间与证伪条件。"
            "\n\n" + DISCLAIMER
        ),
        tools=ALL_FIN_TOOLS,
        model="inherit",
    ),
}
