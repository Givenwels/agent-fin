# Financial Agent Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit financial workflow contracts and final completion checks so complex allocation, rebalance, decision, review, and risk tasks behave more like auditable agent work.

**Architecture:** Keep the current local MCP tool architecture. Add two focused tool modules: `tools/workflows.py` defines workflow contracts, and `tools/checks.py` validates claimed completion before final answers. Wire both into `tools/__init__.py`, `agents.py`, `prompts.py`, playbooks, tests, and README without adding dependencies.

**Tech Stack:** Python 3.11, `claude-agent-sdk`, `mcp.types.ToolAnnotations`, pytest, local JSON/text responses.

---

## File Structure

- Create `tools/workflows.py`: workflow metadata, workflow-type resolver, pure `workflow_contract()` helper, and `start_financial_workflow` MCP tool.
- Create `tools/checks.py`: pure `run_final_check()` helper and `final_task_check` MCP tool.
- Create `tests/test_workflows.py`: workflow/check pure logic tests and registration consistency tests.
- Modify `tools/__init__.py`: import and expose the two new tools.
- Modify `agents.py`: add the two new tool names to `WORKFLOW_TOOLS`.
- Modify `prompts.py`: require workflow start, visible plan updates, final check, and financial boundaries for complex tasks.
- Modify `playbooks/allocation.md`: add workflow/final-check discipline to the allocation flow.
- Modify `playbooks/decision_checklist.md`: add final-check discipline to buy/sell decision flow.
- Modify `README.md`: update positioning, command list if needed, tool count, and workflow behavior.

## Implementation Notes

- Preserve the existing uncommitted planner integration: `tools/planner.py`, `/plan`, `write_plan`, and prompt references.
- Do not touch `memory/` or `portfolio/`.
- Run all tests with `D:\Users\dingm\anaconda3\envs\finagent\python.exe -m pytest -q`, not base Python.
- Keep responses from tools as JSON text in the same MCP content shape used by existing tools.

---

### Task 1: Workflow Contract Tests

**Files:**
- Create: `tests/test_workflows.py`
- Read: `tools/__init__.py`
- Read: `agents.py`

- [ ] **Step 1: Write the failing workflow contract tests**

Add this file:

```python
"""Workflow and final-check tests for agent-like financial task execution."""

from tools.workflows import WORKFLOW_TYPES, workflow_contract


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py -q
```

Expected: FAIL with `ModuleNotFoundError` or import error for `tools.workflows`.

---

### Task 2: Implement Workflow Contracts

**Files:**
- Create: `tools/workflows.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Add `tools/workflows.py`**

Create the file with this content:

```python
"""Financial workflow contracts.

This module gives the model a structured task contract before it starts complex
financial work. It does not execute the workflow; it tells the agent which
steps, tools, checks, and guardrails must be visible before the final answer.
"""

from __future__ import annotations

import json

from claude_agent_sdk import tool

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
)
async def start_financial_workflow(args: dict) -> dict:
    payload = workflow_contract(args.get("workflow_type", ""), args.get("context", ""))
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": bool(payload.get("is_error")),
    }
```

- [ ] **Step 2: Run the workflow tests**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py -q
```

Expected: PASS for the first two workflow tests.

---

### Task 3: Final Check Tests

**Files:**
- Modify: `tests/test_workflows.py`
- Read: `docs/superpowers/specs/2026-06-27-financial-agent-workflow-design.md`

- [ ] **Step 1: Add final-check tests**

Append this code to `tests/test_workflows.py`:

```python
from tools.checks import run_final_check


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
        "decision": ["checklist_loaded", "one_question_at_a_time", "valuation_or_risk_when_useful",
                     "invalidation_conditions", "decision_summary", "journal_offer", "no_direct_order"],
        "review": ["review_data", "board_summary", "risk_summary", "journal_review",
                   "thesis_check", "next_watch_points", "disclaimer"],
        "risk_check": ["holdings_or_dashboard", "risk_diagnosis", "severity_explanation",
                       "directional_improvements", "no_trade_instruction"],
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py -q
```

Expected: FAIL with `ModuleNotFoundError` or import error for `tools.checks`.

---

### Task 4: Implement Final Task Check

**Files:**
- Create: `tools/checks.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Add `tools/checks.py`**

Create the file with this content:

```python
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
```

- [ ] **Step 2: Run the workflow tests**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py -q
```

Expected: PASS for workflow and check tests.

---

### Task 5: Wire Tools and Agent Permissions

**Files:**
- Modify: `tools/__init__.py`
- Modify: `agents.py`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Add registration consistency tests**

Append this code to `tests/test_workflows.py`:

```python
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
```

- [ ] **Step 2: Run the registration test to verify it fails**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py::test_workflow_tools_registered_and_allowed -q
```

Expected: FAIL because the new tools are not yet imported in `tools/__init__.py` and not listed in `agents.py`.

- [ ] **Step 3: Modify `tools/__init__.py`**

Add imports after the existing planner import:

```python
from .workflows import start_financial_workflow
from .checks import final_task_check
```

Change the first line of `ALL_TOOLS` from:

```python
    start_allocation, decision_checklist, write_plan,
```

to:

```python
    start_financial_workflow, final_task_check,
    start_allocation, decision_checklist, write_plan,
```

Change the start of `__all__` from:

```python
    "ALL_TOOLS",
    "start_allocation", "decision_checklist", "write_plan",
```

to:

```python
    "ALL_TOOLS",
    "start_financial_workflow", "final_task_check",
    "start_allocation", "decision_checklist", "write_plan",
```

- [ ] **Step 4: Modify `agents.py`**

Change `WORKFLOW_TOOLS` to:

```python
WORKFLOW_TOOLS = [
    "mcp__fin__start_financial_workflow",
    "mcp__fin__final_task_check",
    "mcp__fin__start_allocation",
    "mcp__fin__decision_checklist",
    "mcp__fin__write_plan",
]
```

- [ ] **Step 5: Run registration tests**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py -q
```

Expected: PASS.

---

### Task 6: Prompt and Playbook Discipline

**Files:**
- Modify: `prompts.py`
- Modify: `playbooks/allocation.md`
- Modify: `playbooks/decision_checklist.md`

- [ ] **Step 1: Update `prompts.py` capability list**

In `CAPABILITIES`, add this after the current decision/review capability:

```python
0f. 显式金融工作流：复杂任务先 start_financial_workflow，再 write_plan 展示计划，过程中更新进度，
   结束前用 final_task_check 自检，确保没有漏掉风险画像、数据来源、持仓对比、纪律和免责。
```

- [ ] **Step 2: Update `prompts.py` tool habits**

In `ALLOCATION_METHODOLOGY`, replace the current planning block:

```python
【规划与自检·像 agent 一样做事】
- 遇到复杂多步任务（一键配置、调仓、周/月复盘等），先用 write_plan 列出步骤计划，
  开始某步前把它标 in_progress、做完标 done，让用户看到你的规划与进度。
- 全部步骤完成后做一次自检：回看计划每步是否真做了、结果是否自洽、有没有漏，再给最终结论。
- 简单的一两步问题不必规划，直接答。
```

with:

```python
【规划与自检·像 agent 一样做事】
- 遇到复杂金融任务（一键配置、调仓、买卖决策、周/月复盘、风险体检），先调
  start_financial_workflow 获取任务合同，再用 write_plan 写入步骤计划。
- 执行时每次只保留一个 in_progress；做完一步就更新为 done，让用户看到你的规划与进度。
- 最终回答前必须调 final_task_check。若检查不通过，先补齐缺项；无法补齐时明确说明限制，
  不要假装任务完整。
- 完整资产配置任务：先 start_financial_workflow(workflow_type=allocation)，再 start_allocation
  加载详细 playbook，然后按计划执行。
- 调仓/待下单清单：generate_order_list 只输出手动参考；必须说明不下单、不连券商、不碰账户，
  大额变化或集中度风险要提示用户再次确认。
- 买入/卖出意图：先 decision_checklist，逐项追问，不替用户拍板；用户实际决策后再建议 add_journal。
- 简单的一两步问题不必规划，直接答。
```

- [ ] **Step 3: Update `playbooks/allocation.md` final steps**

Change the final steps so they include final check:

```markdown
9. **最终自检**
   调 `final_task_check(workflow_type="allocation")`，completed_steps 至少包含：
   `risk_profile`、`framework_or_macro`、`price_data`、`optimization_or_metrics`、
   `holdings_comparison`、`rebalance_discipline`、`invalidation_conditions`、`disclaimer`。
   若检查不通过，先补齐缺项；确实无法完成时在最终输出中说明限制。

10. **存档**
    用 `save_memory`（category=决策，key=配置参考-日期）记下本次参考配置要点，便于以后复盘。
```

- [ ] **Step 4: Update `playbooks/decision_checklist.md` closing section**

Append this bullet to `## 三、收尾`:

```markdown
- 最终总结前调 `final_task_check(workflow_type="decision")`，确认已经加载清单、逐项追问、
  收集证伪条件、没有替用户下买卖命令；若缺项，先继续追问。
```

- [ ] **Step 5: Run a syntax/import check**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m py_compile prompts.py agents.py main.py tools\__init__.py tools\workflows.py tools\checks.py
```

Expected: command exits 0.

---

### Task 7: README Refresh

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README positioning and tool count**

Make these text changes:

```markdown
# agent_fin — 本地金融投研 Agent（资产配置 / 风险体检 / 复盘）
```

Replace the old tool-count paragraph with:

```markdown
**27 个工具，分 8 组**：金融工作流(start_financial_workflow/final_task_check) · 显式计划(write_plan) ·
持仓与看板 · 风险诊断与调仓清单 · 投资日记与复盘 · 记忆 · 知识库 · 数据与量化。
复杂任务会先写计划，可用 `/plan` 查看当前步骤；最终回答前会做 `final_task_check`，
防止漏掉风险画像、数据来源、持仓对比、手动执行边界和免责声明。
```

Add this to the interactive command list if not already present:

```markdown
`/plan` 看当前任务计划
```

Add this boundary statement near the order-list section:

```markdown
调仓清单是手动参考，不连接券商、不下单、不碰账户；最后操作永远由用户自己在自己的 App 里确认。
```

- [ ] **Step 2: Scan README for stale "12 个工具"**

Run:

```powershell
Select-String -Path 'README.md' -Pattern '12 个工具|起步骨架' -Encoding UTF8
```

Expected: no stale `12 个工具`; title may no longer say `起步骨架`.

---

### Task 8: Full Verification and Commit

**Files:**
- Verify all changed files
- Commit all implementation files, including existing planner integration

- [ ] **Step 1: Run focused tests**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest tests/test_workflows.py -q
```

Expected: all workflow tests pass.

- [ ] **Step 2: Run full tests**

Run:

```powershell
& 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run registration smoke check**

Run:

```powershell
@'
from tools import ALL_TOOLS
from agents import ALL_FIN_TOOLS, AGENTS
names = [getattr(t, "name", None) or getattr(t, "__name__", type(t).__name__) for t in ALL_TOOLS]
print("tools", len(ALL_TOOLS))
print("has workflow", "start_financial_workflow" in names)
print("has final check", "final_task_check" in names)
print("missing", [x for x in ALL_FIN_TOOLS if x.removeprefix("mcp__fin__") not in names])
print("agents", list(AGENTS))
'@ | & 'D:\Users\dingm\anaconda3\envs\finagent\python.exe' -
```

Expected:

```text
tools 27
has workflow True
has final check True
missing []
agents ['macro-analyst', 'risk-profiler', 'allocator']
```

- [ ] **Step 4: Check whitespace**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 5: Review diff**

Run:

```powershell
git diff --stat
git diff -- tools/workflows.py tools/checks.py tests/test_workflows.py tools/__init__.py agents.py prompts.py playbooks/allocation.md playbooks/decision_checklist.md README.md
```

Expected: only the workflow/check implementation, prompt/playbook/docs updates, tests, and existing planner integration are present.

- [ ] **Step 6: Commit**

Run:

```powershell
git add agents.py main.py prompts.py README.md playbooks/allocation.md playbooks/decision_checklist.md tools/__init__.py tools/planner.py tools/workflows.py tools/checks.py tests/test_workflows.py
git commit -m "feat: add financial workflow checks"
```

Expected: commit succeeds. The pre-existing planner integration is included because it is part of the visible workflow behavior this feature depends on.
