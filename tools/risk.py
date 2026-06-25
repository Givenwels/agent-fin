"""持仓风险诊断（P3：让 agent 从"问答"变成"盯风险的助理"）。

═══════════════════════════════════════════════════════════════════════
规则引擎：读已存持仓 → 用阈值规则查"集中度/现金"等结构性风险 → 给提示与改善方向。
只做诊断与教育，不给确定性买卖指令、不承诺收益。阈值可用环境变量覆盖。
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import os

from claude_agent_sdk import tool

from .holdings import _load, compute_board

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None


def _thr(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# 阈值（百分比），可用环境变量覆盖
SINGLE_MAX = _thr("FIN_RISK_SINGLE_MAX", 30)   # 单一持仓占比上限
CLASS_MAX = _thr("FIN_RISK_CLASS_MAX", 70)     # 单一大类占比上限
SECTOR_MAX = _thr("FIN_RISK_SECTOR_MAX", 40)   # 单一行业占比上限
CASH_MIN = _thr("FIN_RISK_CASH_MIN", 5)        # 现金比例下限


def evaluate_risk(b: dict) -> list[dict]:
    """对组合画像（compute_board 的输出）跑规则，返回风险提示列表。诊断与复盘共用。"""
    warnings: list[dict] = []

    # 1) 单一资产占比过高
    th = b["top_holding"]
    if th["pct"] > SINGLE_MAX:
        warnings.append({
            "level": "高" if th["pct"] > SINGLE_MAX + 20 else "中",
            "issue": "单一资产占比过高",
            "detail": f"{th['name']} 占 {th['pct']}%（阈值 {SINGLE_MAX}%）",
            "suggestion": "单一标的波动会主导整个组合，可考虑适度分散，降低对它的依赖。",
        })

    # 2) 大类过于集中
    for c in b["by_class"]:
        if c["pct"] > CLASS_MAX:
            warnings.append({
                "level": "中",
                "issue": "大类集中",
                "detail": f"{c['class']} 占 {c['pct']}%（阈值 {CLASS_MAX}%）",
                "suggestion": "单一大类占比过高时，组合的攻防失衡；可参考矛/盾思路提高其它大类。",
            })

    # 3) 行业集中度过高（注意行业覆盖率，数据不全时降级提示）
    cov = b["sector_covered_pct"]
    for s in b["by_sector"]:
        if s["pct"] > SECTOR_MAX:
            note = "" if cov >= 80 else f"（注：仅 {cov}% 持仓标了行业，结论可能不全）"
            warnings.append({
                "level": "中",
                "issue": "行业集中度过高",
                "detail": f"{s['sector']} 占 {s['pct']}%（阈值 {SECTOR_MAX}%）{note}",
                "suggestion": "行业景气下行时集中持有风险大，可考虑跨行业分散。",
            })

    # 4) 现金比例过低
    if b["cash_ratio"] < CASH_MIN:
        warnings.append({
            "level": "中",
            "issue": "现金比例过低",
            "detail": f"现金/货基占 {b['cash_ratio']}%（下限 {CASH_MIN}%）",
            "suggestion": "现金过低会削弱应急与逢低补仓的能力，可考虑留出流动性缓冲。",
        })
    return warnings


@tool(
    "diagnose_risk",
    "诊断当前持仓的结构性风险：单一资产占比过高、大类过于集中、行业集中度过高、现金比例过低。"
    "返回风险提示与改善方向（非买卖指令）。用户问'我的组合有什么风险'时调用。",
    {},
    annotations=_RO,
)
async def diagnose_risk(args: dict) -> dict:
    items = _load()
    if not items:
        return {"content": [{"type": "text",
                "text": "组合为空，先用 add_holding 录入持仓后再诊断。"}]}

    b = compute_board(items)
    warnings = evaluate_risk(b)

    result = {
        "total": b["total"],
        "checked": ["单一资产占比", "大类集中度", "行业集中度", "现金比例"],
        "warnings": warnings,
        "all_clear": len(warnings) == 0,
        "disclaimer": "以上为结构性风险提示与方向，非个性化投资建议，不构成买卖指令，决策与风险自负。",
    }
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
