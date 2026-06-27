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

from tools.holdings import _load, compute_board
from tools.review import _compare, _latest_prior_snapshot, _save_snapshot
from tools.risk import evaluate_risk

ALERT_DIR = Path(__file__).resolve().parent / "portfolio" / "alerts"
DRIFT_ALERT_PCT = 10.0  # 总值较上次变化超过此值也提示


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


if __name__ == "__main__":
    sys.exit(run_watch())
