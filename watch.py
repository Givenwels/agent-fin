r"""定时风险监控（主动型能力）——不依赖 LLM，纯规则，可挂系统计划任务定时跑。

读已存持仓 → 跑风险规则 + 与上次快照对比 → 有问题就写告警到 portfolio/alerts/ →
下次打开 agent（main.py）会主动把告警提示给你。退出码 = 风险提示条数（计划任务可据此通知）。

手动跑：python watch.py
定时跑：Windows 任务计划程序里加一条，每天执行
  D:\Users\dingm\anaconda3\envs\finagent\python.exe F:\vibecoding\agent_fin\watch.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 控制台 UTF-8（计划任务里默认 GBK，避免中文乱码）
try:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from tools.holdings import _load, compute_board
from tools.review import _compare, _latest_prior_snapshot, _save_snapshot
from tools.risk import evaluate_risk

ALERT_DIR = Path(__file__).resolve().parent / "portfolio" / "alerts"
DRIFT_ALERT_PCT = 10.0  # 总值较上次变化超过此值也提示

# 心跳（--agent）只读工具集：autonomous 运行时绝不让它改持仓/记忆
MONITOR_TOOL_NAMES = {
    "list_holdings", "portfolio_dashboard", "diagnose_risk",
    "get_macro_indicator", "get_valuation", "get_news",
    "get_price_history", "calc_portfolio_metrics",
}

MONITOR_SYSTEM = (
    "你是组合风险监控助手，正在做一次【自主体检】（不是用户提问）。下面会给你用户的真实持仓画像"
    "与规则引擎的风险结果。任务：必要时用只读工具（diagnose_risk/get_macro_indicator/get_valuation/"
    "get_news）补充判断，然后写一段**简短**告警（≤200字）：①风险严重度 ②1-2 个最该关注的点 "
    "③1 个方向性关注事项（不是买卖指令）。结尾一句免责。不下单、不接券商、不碰账户。"
)


def run_watch() -> int:
    """跑一次监控，返回风险提示条数。"""
    items = _load()
    if not items:
        print("组合为空，无需监控（先用 agent 录入持仓）。")
        return 0

    board = compute_board(items)
    warns = evaluate_risk(board)
    prev = _latest_prior_snapshot()
    cmp = _compare(board, prev) if prev else None
    big_drift = bool(cmp and abs(cmp["total_change_pct"]) >= DRIFT_ALERT_PCT)

    lines = [f"# 风险监控 · {datetime.now():%Y-%m-%d %H:%M}", "",
             f"组合总值 {board['total']} 元，共 {board['count']} 笔"]
    if cmp:
        lines.append(f"较上次({cmp['prev_date']})总值变化 {cmp['total_change_pct']:+.1f}%"
                     + ("  ⚠️ 波动较大" if big_drift else ""))
    lines.append("\n## 结构性风险")
    if warns:
        for w in warns:
            lines.append(f"- [{w['level']}] {w['issue']}：{w['detail']}")
    else:
        lines.append("- 无（单一持仓/大类/行业/现金 各项均在阈值内）")
    report = "\n".join(lines)

    # 留存：归档一份 + 若有风险/大漂移则写 latest.md 供下次开 agent 提示
    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    (ALERT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.md").write_text(report, encoding="utf-8")
    latest = ALERT_DIR / "latest.md"
    if warns or big_drift:
        latest.write_text(report, encoding="utf-8")
    elif latest.exists():
        latest.unlink()  # 风险解除则清掉旧提示

    _save_snapshot(board)  # 存当日快照，供下次对比

    print(report)
    flagged = warns or big_drift
    print(f"\n[监控完成] 风险提示 {len(warns)} 条"
          + ("，已留待下次打开 agent 时提示。" if flagged else "，一切正常。"))
    return len(warns)


def _build_monitor_task(board: dict, warns: list, cmp: dict | None) -> str:
    """把真实持仓 + 规则结果打包成给 agent 的体检输入。"""
    import json
    lines = [
        "【组合画像】" + json.dumps(board, ensure_ascii=False),
        "【规则风险结果】" + (json.dumps(warns, ensure_ascii=False) if warns else "无规则级风险"),
    ]
    if cmp:
        lines.append("【较上次快照】" + json.dumps(cmp, ensure_ascii=False))
    lines.append("请据此做一次自主体检并写简短告警。")
    return "\n".join(lines)


async def run_agent_watch(always: bool = False) -> int:
    """心跳模式：规则体检 + 让 agent 自主深度体检 + 写告警 + 桌面推送。"""
    items = _load()
    if not items:
        print("组合为空，无需监控（先用 agent 录入持仓）。")
        return 0

    board = compute_board(items)
    warns = evaluate_risk(board)
    prev = _latest_prior_snapshot()
    cmp = _compare(board, prev) if prev else None
    big_drift = bool(cmp and abs(cmp["total_change_pct"]) >= DRIFT_ALERT_PCT)
    flagged = bool(warns or big_drift)
    _save_snapshot(board)  # 存当日快照供下次对比

    latest = ALERT_DIR / "latest.md"
    if not flagged and not always:
        print("规则体检无异常，未触发 agent 深度体检（加 --always 可强制每次都跑）。")
        if latest.exists():
            latest.unlink()  # 风险解除，清掉旧提示
        return 0

    # 让 agent 自己醒来做一次体检
    import engine
    from tools import ALL_TOOLS
    from tools.reporting import export_report_file, notify

    mon = [t for t in ALL_TOOLS if t.name in MONITOR_TOOL_NAMES]
    schema = engine.build_tool_schemas(mon)
    by_name = {t.name: t for t in mon}

    client = engine.build_client()
    messages = [{"role": "user", "content": _build_monitor_task(board, warns, cmp)}]
    print("🫀 agent 正在自主体检…\n")
    try:
        await engine.run_turn(
            client, MONITOR_SYSTEM, messages,
            on_text=lambda t: print(t, end="", flush=True),
            on_tool=lambda n: print(f"\n  〔调用 {n}〕", flush=True),
            tools_schema=schema, tool_by_name=by_name,
            allow_delegate=False, max_iters=10,
        )
    finally:
        close = getattr(client, "close", None)
        if close:
            try:
                await close()
            except Exception:
                pass

    narrative = engine._last_assistant_text(messages) or "（agent 未产出文本）"
    report = (f"# 风险监控 · agent 体检 · {datetime.now():%Y-%m-%d %H:%M}\n\n"
              f"组合总值 {board['total']} 元，共 {board['count']} 笔\n\n{narrative}")
    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    (ALERT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-agent.md").write_text(report, encoding="utf-8")
    latest.write_text(report, encoding="utf-8")  # 下次开 agent 自动顶出
    export_report_file("风险监控", report, "md")  # 同时存一份到 reports/

    first = next((ln for ln in narrative.splitlines() if ln.strip()), "组合体检已完成")
    notify("组合风险提示" if flagged else "组合体检完成", first[:200])
    print(f"\n\n[心跳完成] 已写 alerts/latest.md + reports/，并尝试桌面推送。规则风险 {len(warns)} 条。")
    return len(warns)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--agent" in argv:
        import asyncio
        sys.exit(asyncio.run(run_agent_watch(always="--always" in argv)))
    sys.exit(run_watch())
