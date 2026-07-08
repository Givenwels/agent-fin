"""宏观指标 + 指数估值分位工具（数据原语，扩展 agent 的"万能"度）。

═══════════════════════════════════════════════════════════════════════
对照源码：和 WebFetchTool 同类——拿外部数据→处理→返回。这里把"判宏观/估值"
  从纯文本判断升级成有真数据支撑：利率/CPI/PMI/M2 给宏观环境，PE/PB 分位答"贵不贵"。
═══════════════════════════════════════════════════════════════════════

说明：数据全部来自 akshare（东方财富/乐咕乐股等国内源），已自动绕过代理。
  这些是实时数据，无离线样本——取不到时返回清晰错误（让 agent 如实说明、不编）。
  注意：函数返回列名可能随 akshare 版本变化，已做动态识别 + 失败兜底。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
from .base import tool

from .market import _bypass_proxy  # 复用：国内数据源绕过 Clash 代理

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
except Exception:  # pragma: no cover
    _RO = None


# 宏观指标关键词 → akshare 函数名
_MACRO_FUNCS = {
    "LPR": "macro_china_lpr",
    "国债收益率": "bond_china_yield",
    "CPI": "macro_china_cpi_yearly",
    "PPI": "macro_china_ppi",
    "PMI": "macro_china_pmi_yearly",
    "M2": "macro_china_money_supply",
}
_MACRO_ALIASES = {
    "lpr": "LPR", "贷款利率": "LPR", "利率": "LPR",
    "国债": "国债收益率", "收益率": "国债收益率", "bond": "国债收益率",
    "cpi": "CPI", "通胀": "CPI",
    "ppi": "PPI",
    "pmi": "PMI", "采购经理": "PMI",
    "m2": "M2", "货币": "M2", "money": "M2", "货币供应": "M2",
}


def _resolve_macro(indicator: str) -> str | None:
    ind = indicator.strip()
    if ind in _MACRO_FUNCS:
        return ind
    low = ind.lower()
    for k, v in _MACRO_ALIASES.items():
        if k in low:
            return v
    return None


def _call_with_optional_dates(fn):
    """有些 akshare 函数需要 start_date/end_date，先试无参，TypeError 再带日期。"""
    try:
        return fn()
    except TypeError:
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=400)).strftime("%Y%m%d")
        return fn(start_date=start, end_date=end)


@tool(
    "get_macro_indicator",
    "获取中国宏观指标的最近数据。indicator 取：LPR(贷款利率)/国债收益率/CPI/PPI/PMI/M2(货币供应)。"
    "用于给『判断宏观环境』提供真实数据支撑。",
    {"indicator": str},
    annotations=_RO,
)
async def get_macro_indicator(args: dict) -> dict:
    ind = _resolve_macro(str(args.get("indicator", "")))
    if ind is None:
        return {"content": [{"type": "text",
                "text": f"不支持的指标。可选：{', '.join(_MACRO_FUNCS)}"}], "isError": True}

    try:
        import akshare as ak
    except Exception:
        return {"content": [{"type": "text", "text": "未安装 akshare，无法获取宏观数据。"}],
                "isError": True}

    try:
        fn = getattr(ak, _MACRO_FUNCS[ind])
        with _bypass_proxy():
            df = _call_with_optional_dates(fn)
        if df is None or len(df) == 0:
            return {"content": [{"type": "text", "text": f"{ind} 返回空数据。"}], "isError": True}
        tail = df.tail(8)
        table = tail.to_string(index=False)
        return {"content": [{"type": "text",
                "text": f"【{ind}】最近数据（来源 akshare）：\n{table}"}]}
    except Exception as e:
        return {"content": [{"type": "text",
                "text": f"获取 {ind} 失败（{type(e).__name__}: {str(e)[:80]}）。"
                        f"可能是网络/代理/数据源变动，请稍后重试或在本地终端确认。"}],
                "isError": True}


# ── 指数估值分位 ─────────────────────────────────────────────────────
def _pick_value_column(df, metric: str):
    """挑主估值列：优先『市值加权 + 滚动(TTM)』，避开『等权』『静态』。

    乐咕乐股的估值表常含多列（等权静态/静态/等权滚动/滚动 市盈率）。普通人说的
    指数 PE 是市值加权 TTM（如沪深300≈12-13），而非等权（会高很多），故须避开"等权"。"""
    key = "市盈率" if metric == "PE" else "市净率"
    cands = [c for c in df.columns if key in str(c)]
    if not cands:
        cands = [c for c in df.columns if df[c].dtype.kind in "fi"]
    if not cands:
        return None

    def score(c) -> int:
        s = str(c)
        sc = 0
        if "滚动" in s or "ttm" in s.lower():
            sc += 2          # TTM 优先于静态
        if "等权" not in s:
            sc += 1          # 市值加权优先于等权
        return sc

    return max(cands, key=score)


@tool(
    "get_valuation",
    "获取宽基指数的估值（PE/PB）当前值与历史分位，回答『现在贵不贵』。symbol 如 "
    "沪深300/上证50/中证500/创业板指/科创50；metric 取 PE 或 PB。",
    {"symbol": str, "metric": str},
    annotations=_RO,
    required=(),
)
async def get_valuation(args: dict) -> dict:
    symbol = str(args.get("symbol", "")).strip() or "沪深300"
    metric = str(args.get("metric", "PE")).strip().upper()
    metric = "PB" if metric == "PB" else "PE"

    try:
        import akshare as ak
    except Exception:
        return {"content": [{"type": "text", "text": "未安装 akshare，无法获取估值。"}],
                "isError": True}

    fn_name = "stock_index_pe_lg" if metric == "PE" else "stock_index_pb_lg"
    try:
        fn = getattr(ak, fn_name)
        with _bypass_proxy():
            df = fn(symbol=symbol)
        if df is None or len(df) < 10:
            return {"content": [{"type": "text",
                    "text": f"{symbol} 的{metric}数据不足或为空。"}], "isError": True}

        col = _pick_value_column(df, metric)
        if col is None:
            # 无法识别估值列，把尾部原样给 LLM 解读
            return {"content": [{"type": "text",
                    "text": f"【{symbol} {metric}】（未能自动识别估值列，原始数据尾部）：\n"
                            + df.tail(5).to_string(index=False)}]}

        series = df[col].astype(float).dropna().to_numpy()
        current = float(series[-1])
        pct = float((series <= current).sum() / len(series) * 100)
        years = round(len(series) / 250, 1)
        if pct >= 80:
            judge = "偏贵（历史高位区）"
        elif pct <= 20:
            judge = "偏便宜（历史低位区）"
        else:
            judge = "估值中性"
        payload = {
            "symbol": symbol, "metric": metric, "column": str(col),
            "current": round(current, 2),
            "percentile": round(pct, 1),
            "history_years": years,
            "judgement": judge,
            "note": "分位=当前值在历史样本中的百分位，越高越贵；仅供参考，不构成投资建议。",
        }
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
    except Exception as e:
        return {"content": [{"type": "text",
                "text": f"获取 {symbol} {metric} 估值失败（{type(e).__name__}: {str(e)[:80]}）。"
                        f"symbol 需用中文宽基名（如 沪深300）；或网络/代理问题，请本地终端确认。"}],
                "isError": True}
