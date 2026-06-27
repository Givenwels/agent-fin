# Financial Agent Workflow Design

Date: 2026-06-27

## Goal

Upgrade `agent_fin` from a capable financial tool collection into a more agent-like local financial assistant. The next change should make complex financial tasks visible, staged, auditable, and bounded by investor-discipline guardrails.

The primary focus is workflow behavior, not adding more market data sources. The agent should plan before multi-step work, update progress while working, verify required financial checks before final answers, and avoid drifting into buy/sell instructions.

## Current Context

The project already has the core agent pieces:

- `main.py` builds a Claude Agent SDK client with an in-process `fin` MCP server, allowed tools, system prompt, child agents, and REPL commands.
- `tools/` exposes 25 tools across holdings, journal, review, memory, knowledge base, macro/valuation data, market data, portfolio math, order-list calculation, playbooks, and planning.
- `agents.py` defines `macro-analyst`, `risk-profiler`, and `allocator`.
- `playbooks/` contains allocation and decision-checklist workflows.
- `watch.py` provides non-LLM scheduled risk monitoring.
- Tests currently cover pure logic and pass in the `finagent` environment.

There is already an uncommitted planner integration: `tools/planner.py`, `write_plan`, `/plan`, and prompt guidance. This design builds on that direction.

## Non-Goals

- Do not connect brokers or place orders.
- Do not add automatic trading, automatic portfolio changes, or account access.
- Do not add a web UI in this iteration.
- Do not add heavyweight optimizers or paid data sources in this iteration.
- Do not write to the external Obsidian knowledge base.

## Recommended Approach

Implement a small workflow layer and financial completion checks:

1. Add reusable workflow templates for common financial task types.
2. Add a validation/self-check tool that evaluates whether a complex financial response completed the required steps.
3. Strengthen prompts and playbooks so complex tasks must use planning, progress updates, and final validation.
4. Add light guardrail helpers for high-risk actions such as buy/sell decisions, rebalance order lists, and destructive local data operations.

This keeps the system close to its current architecture: local files, small tools, clear prompts, and pure Python tests.

## User-Facing Behavior

For complex tasks, the agent should behave like this:

1. Classify the task type.
2. Write a plan with `write_plan`.
3. Mark one step `in_progress` at a time.
4. Use the domain tools needed for that step.
5. Mark completed steps as `done`.
6. Run a final self-check before the final answer.
7. Report missing assumptions, data failures, risks, and compliance boundaries.

Simple questions still answer directly. Examples of simple questions:

- "沪深300现在贵不贵？"
- "你记得我什么？"
- "/portfolio"

Examples of complex tasks:

- "帮我做一套稳健型资产配置"
- "帮我把当前组合调到 40/40/20"
- "帮我做月度复盘"
- "我想买这个基金，帮我判断一下"
- "我的组合现在风险怎么样，下一步该关注什么"

## Workflow Types

### Allocation Workflow

Required steps:

- Confirm or recall risk profile and investment goal.
- Retrieve relevant framework or macro context when needed.
- Fetch price data for candidate assets.
- Run optimization or metrics.
- Compare against current holdings when holdings exist.
- Provide rebalance discipline and evidence-based invalidation conditions.
- Include the standard disclaimer.
- Store a memory or journal entry only when appropriate and user-relevant.

### Rebalance Workflow

Required steps:

- Read current holdings.
- Normalize target weights.
- Generate an order list as a manual reference only.
- Run structural risk diagnosis against the resulting target idea when possible.
- Flag large changes, concentration, low cash, or missing assets.
- Ask the user to confirm before they manually act.
- Make clear that no order is placed.

### Decision Checklist Workflow

Required steps:

- Load the decision checklist.
- Ask one question at a time.
- Use valuation, risk, or holdings tools when useful.
- Ask for three invalidation conditions.
- Summarize decision logic and risks.
- Offer to record a journal entry after the user makes a decision.

### Review Workflow

Required steps:

- Load review report data.
- Summarize current board, risks, journal items, and snapshot comparison.
- Identify whether prior thesis conditions were confirmed or invalidated when data exists.
- Provide next-period watch points rather than buy/sell instructions.
- Include the standard disclaimer.

### Risk Check Workflow

Required steps:

- Read holdings or dashboard.
- Run risk diagnosis.
- Explain warnings by severity.
- Suggest direction-level improvements without issuing trade commands.
- If user asks for concrete target weights, transition to allocation or rebalance workflow.

## New Components

### `tools/workflows.py`

Purpose: expose workflow templates and task-type metadata to the agent.

Tools:

- `start_financial_workflow`

Inputs:

- `workflow_type`: one of `allocation`, `rebalance`, `decision`, `review`, `risk_check`
- `context`: short user request summary

Output:

- required steps
- required tools
- completion checklist
- guardrail notes

This does not execute the workflow. It gives the model a structured contract to follow.

### `tools/checks.py`

Purpose: provide a deterministic final checklist for complex financial tasks.

Tools:

- `final_task_check`

Inputs:

- `workflow_type`
- `completed_steps`: list of step names or checklist ids the agent believes it completed
- `used_tools`: list of relevant tool names
- `notes`: brief summary of assumptions, failures, and unresolved items

Output:

- `passed`: boolean
- `missing`: list of missing required checks
- `warnings`: list of compliance or workflow warnings
- `final_instruction`: short guidance for the final response

The check is not a legal/compliance engine. It is a simple guard against skipped steps and overconfident financial conclusions.

### Prompt Updates

Update `prompts.py` so the agent follows these rules:

- For complex financial tasks, call `start_financial_workflow` first unless a playbook was already loaded.
- Use `write_plan` before executing the workflow.
- Update the plan as work progresses.
- Call `final_task_check` before final answer.
- If `final_task_check` fails, either complete the missing step or clearly state what could not be completed.
- Never present `generate_order_list` output as an instruction to trade.
- For buy/sell intent, load `decision_checklist` and proceed one question at a time.

### Agent Tool Lists

Update `agents.py` so workflow-related tools are available to the relevant agents:

- `start_financial_workflow`
- `final_task_check`
- existing `write_plan`
- existing playbook tools

The allocator should have access to all workflow and check tools. The main agent should be allowed to call them directly.

### README Updates

Update README to describe the current tool count and the new workflow behavior:

- "25+ tools" instead of "12 tools"
- visible planning with `/plan`
- workflow self-checks
- manual-only rebalance order list
- no broker connection and no automatic order placement

## Data Flow

For a complex allocation request:

1. User asks for allocation.
2. Agent calls `start_financial_workflow(workflow_type="allocation")`.
3. Agent calls `write_plan` with the returned steps.
4. Agent performs each step using current tools.
5. Agent calls `final_task_check`.
6. Agent either fixes missing items or gives a final answer with limitations.

For a rebalance request:

1. User gives target weights.
2. Agent calls `start_financial_workflow(workflow_type="rebalance")`.
3. Agent reads holdings and writes plan.
4. Agent calls `generate_order_list`.
5. Agent flags risk and manual-only execution boundaries.
6. Agent calls `final_task_check`.
7. Agent gives a reference list and asks for user confirmation before any record update.

## Error Handling

- If holdings are empty, the workflow should stop and ask the user to record holdings first.
- If market data fails, the final response must state whether offline sample data was used.
- If knowledge base search fails, the agent should state that the framework source could not be retrieved.
- If `final_task_check` reports missing required steps, the agent should not pretend the task is complete.
- If a user asks for direct buy/sell orders, the agent should route to decision checklist and explain boundaries.

## Testing

Add focused tests for pure logic:

- `start_financial_workflow` returns required steps for each workflow type.
- Unknown workflow type returns an error.
- `final_task_check` passes when required steps are present.
- `final_task_check` reports missing allocation, rebalance, decision, review, and risk-check requirements.
- Guardrail warning appears when rebalance/check inputs include order-list usage without manual-only note.

Existing tests should continue to pass in the `finagent` environment.

## Implementation Scope

Files likely to change:

- `tools/workflows.py`
- `tools/checks.py`
- `tools/__init__.py`
- `agents.py`
- `prompts.py`
- `main.py` only if `/help` needs wording changes
- `README.md`
- `tests/test_core.py` or a new focused test file

This is a medium-sized feature, but it stays inside the existing architecture and does not require new dependencies.

## Success Criteria

- The agent has an explicit workflow-start tool and final-check tool.
- Complex financial tasks are guided by a visible plan.
- The final answer for allocation/rebalance/review/decision tasks has a completion check.
- Rebalance outputs are clearly manual reference lists, not order instructions.
- Tests pass with `D:\Users\dingm\anaconda3\envs\finagent\python.exe -m pytest -q`.
- README accurately reflects current behavior and tool count.
