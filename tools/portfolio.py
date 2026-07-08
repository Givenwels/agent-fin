"""组合分析与配置优化工具（纯 numpy/pandas，无外部数据依赖，必定可运行）。

═══════════════════════════════════════════════════════════════════════
对照源码：这类「拿到输入→纯计算→返回结果」的工具，结构等同
  restored-src/src/tools/BashTool 这类工具——重点都在 call() 的逻辑本身。
  schema 里用 list/dict 字段 ≈ 复杂 inputSchema（源码里用 zod object）。
═══════════════════════════════════════════════════════════════════════

设计约定：returns_data 是 {symbol: [日收益, ...]} 字典，
通常由 get_price_history 的输出里的 daily_returns 喂进来。
"""

from __future__ import annotations

import json

import numpy as np
from .base import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
except Exception:  # pragma: no cover
    _RO = None

TRADING_DAYS = 252


def _returns_from_cache(symbols: list[str]) -> tuple[dict, list[str]]:
    """从行情缓存按 symbol 取日收益（上下文控制：数字不经过模型）。
    返回 (returns_data, 缺失的symbols)。缺失的需先调 get_price_history。"""
    from .market import load_price_cache
    data, missing = {}, []
    for s in symbols:
        c = load_price_cache(s)
        if c and c.get("daily_returns"):
            data[s] = c["daily_returns"]
        else:
            missing.append(s)
    return data, missing


# ───────────────────────── 公共：把 returns_data 对齐成矩阵 ─────────────────────────
def _align(symbols: list[str], returns_data: dict) -> tuple[list[str], np.ndarray]:
    """返回 (有效symbols, 形状[T, N] 的日收益矩阵)。按最短长度对齐截断。"""
    series: dict[str, np.ndarray] = {}
    for sym in symbols:
        raw = returns_data.get(sym)
        if isinstance(raw, dict):  # 容错：万一传进来整个 payload
            raw = raw.get("daily_returns")
        if raw:
            series[sym] = np.asarray(raw, dtype=float)
    if not series:
        return [], np.empty((0, 0))
    min_len = min(len(v) for v in series.values())
    valid = [s for s in symbols if s in series]
    mat = np.column_stack([series[s][-min_len:] for s in valid])
    return valid, mat


def _metrics(port_daily: np.ndarray, rf: float = 0.0) -> dict:
    """给定组合的日收益序列，算年化收益/波动/夏普/最大回撤。"""
    ann_ret = float(port_daily.mean() * TRADING_DAYS)
    ann_vol = float(port_daily.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(port_daily) > 1 else 0.0
    sharpe = float((ann_ret - rf) / ann_vol) if ann_vol > 1e-9 else 0.0
    curve = np.cumprod(1.0 + port_daily)
    peak = np.maximum.accumulate(curve)
    max_dd = float(((curve - peak) / peak).min()) if len(curve) else 0.0
    return {
        "annualized_return": round(ann_ret, 4),
        "annualized_volatility": round(ann_vol, 4),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
    }


# ───────────────────────────── 工具 1：组合指标 ─────────────────────────────
@tool(
    "calc_portfolio_metrics",
    "给定标的与权重，计算组合的年化收益、年化波动、夏普比率、最大回撤及各标的风险贡献占比。"
    "日收益数据自动从缓存读取——先对每个标的调 get_price_history 即可，无需传收益数字。",
    {"symbols": list, "weights": list},
    annotations=_RO,
)
async def calc_portfolio_metrics(args: dict) -> dict:
    symbols = list(args.get("symbols") or [])
    weights = np.asarray(args.get("weights") or [], dtype=float)
    returns_data, missing = _returns_from_cache(symbols)
    if missing:
        return {"content": [{"type": "text",
                "text": f"以下标的暂无缓存数据，请先对它们调 get_price_history：{', '.join(missing)}"}],
                "isError": True}

    valid, mat = _align(symbols, returns_data)
    if mat.size == 0:
        return {"content": [{"type": "text", "text": "错误：无有效收益数据。"}],
                "isError": True}
    if len(weights) != len(valid):
        return {"content": [{"type": "text",
                "text": f"错误：weights 数量({len(weights)})与有效标的({len(valid)})不一致。"}],
                "isError": True}

    weights = weights / weights.sum()  # 归一化
    port_daily = mat @ weights
    cov = np.cov(mat, rowvar=False) * TRADING_DAYS
    port_var = float(weights @ cov @ weights)
    mrc = cov @ weights
    rc = weights * mrc
    rc_pct = (rc / rc.sum()) if rc.sum() != 0 else rc

    out = {
        "symbols": valid,
        "weights": [round(float(w), 4) for w in weights],
        **_metrics(port_daily),
        "risk_contribution_pct": {
            s: round(float(p), 4) for s, p in zip(valid, rc_pct)
        },
    }
    return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}


# ───────────────────────────── 工具 2：组合优化 ─────────────────────────────
def _max_sharpe_montecarlo(mu: np.ndarray, cov: np.ndarray, n: int = 30000) -> np.ndarray:
    """长仓约束下的最大夏普——蒙特卡洛采样（无需 scipy，稳健）。"""
    rng = np.random.default_rng(7)
    k = len(mu)
    best_w, best_sharpe = np.ones(k) / k, -np.inf
    for _ in range(n):
        w = rng.random(k)
        w /= w.sum()
        ret = w @ mu
        vol = np.sqrt(w @ cov @ w)
        s = ret / vol if vol > 1e-9 else -np.inf
        if s > best_sharpe:
            best_sharpe, best_w = s, w
    return best_w


def _risk_parity(cov: np.ndarray, iters: int = 5000) -> np.ndarray:
    """风险平价——带阻尼的乘法迭代，收敛到各标的风险贡献相等（长仓、权重和=1）。

    每步把风险贡献偏低的标的权重上调、偏高的下调：
        w_i *= sqrt( 平均风险贡献 / 该标的风险贡献 )
    sqrt 阻尼保证稳定收敛（业界常用做法）。
    """
    k = cov.shape[0]
    w = np.ones(k) / k
    for _ in range(iters):
        rc = w * (cov @ w)                      # 各标的风险贡献（未归一）
        w_new = w * np.sqrt(rc.mean() / np.maximum(rc, 1e-12))
        w_new /= w_new.sum()
        if np.max(np.abs(w_new - w)) < 1e-10:
            w = w_new
            break
        w = w_new
    return w


@tool(
    "optimize_portfolio",
    "按某方法求解一组『参考权重』(用于教育/对比，非买卖建议)。method 取 'mean_variance'(最大夏普) "
    "或 'risk_parity'(风险平价/各标的风险贡献相等)。返回参考权重与组合指标，供与用户当前持仓对比理解。"
    "日收益自动从缓存读取——先对每个标的调 get_price_history 即可，无需传收益数字。",
    {"symbols": list, "method": str},
    annotations=_RO,
    required=("symbols",),
)
async def optimize_portfolio(args: dict) -> dict:
    symbols = list(args.get("symbols") or [])
    method = str(args.get("method") or "risk_parity").strip().lower()
    returns_data, missing = _returns_from_cache(symbols)
    if missing:
        return {"content": [{"type": "text",
                "text": f"以下标的暂无缓存数据，请先对它们调 get_price_history：{', '.join(missing)}"}],
                "isError": True}

    valid, mat = _align(symbols, returns_data)
    if mat.size == 0 or mat.shape[1] < 2:
        return {"content": [{"type": "text", "text": "错误：至少需要 2 个有效标的的缓存数据。"}],
                "isError": True}

    mu = mat.mean(axis=0) * TRADING_DAYS
    cov = np.cov(mat, rowvar=False) * TRADING_DAYS

    if method in ("mean_variance", "max_sharpe", "mv"):
        w = _max_sharpe_montecarlo(mu, cov)
        used = "mean_variance(最大夏普)"
    else:
        w = _risk_parity(cov)
        used = "risk_parity(风险平价)"

    port_daily = mat @ w
    out = {
        "method": used,
        "symbols": valid,
        "weights": {s: round(float(x), 4) for s, x in zip(valid, w)},
        **_metrics(port_daily),
        "用途": "这是该方法下的『参考配置』，用于理解不同方法的风险收益权衡、或与你当前持仓对比，"
                "非买卖建议；实际取舍结合你的风险画像，决策与风险自负。",
    }
    return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
