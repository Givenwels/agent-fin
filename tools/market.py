"""行情数据工具。

═══════════════════════════════════════════════════════════════════════
对照源码：restored-src/src/tools/WebFetchTool/WebFetchTool.ts
  - @tool(name, desc, schema)      ≈ Tool.name / prompt() / inputSchema
  - async def 函数体                ≈ Tool.call()           （真正干活）
  - readOnlyHint=True              ≈ Tool.isReadOnly()      （只读→不弹权限）
  - 数据源失败返回文本而非抛异常     ≈ WebFetchTool 的 redirect/error 分支
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager

import numpy as np
from claude_agent_sdk import tool

try:
    from mcp.types import ToolAnnotations
except Exception:  # pragma: no cover - mcp 总是随 sdk 安装，这里只是兜底
    ToolAnnotations = None


# ─────────────────────────────────────────────────────────────────────
# 离线示例数据：保证「没网 / 没装 akshare」时骨架照样能演示完整链路。
# 用固定随机种子生成 ~1 年日收益，参数贴近各资产真实风险收益特征。
# ─────────────────────────────────────────────────────────────────────
def _make_sample_returns() -> dict[str, list[float]]:
    rng = np.random.default_rng(42)
    n = 250  # 约一年交易日
    specs = {
        # symbol: (名称, 年化收益, 年化波动)
        "510300": ("沪深300ETF", 0.08, 0.20),
        "511010": ("国债ETF", 0.03, 0.04),
        "518880": ("黄金ETF", 0.06, 0.15),
        "513100": ("纳指ETF", 0.12, 0.25),
    }
    out: dict[str, list[float]] = {}
    for sym, (_name, mu, sigma) in specs.items():
        daily_mu = mu / 252
        daily_sigma = sigma / np.sqrt(252)
        r = rng.normal(0, 1, n)
        # 重定标：让样本均值/标准差精确等于目标值，避免小样本噪声让演示反直觉
        r = (r - r.mean()) / r.std() * daily_sigma + daily_mu
        out[sym] = [round(float(x), 6) for x in r]
    return out


SAMPLE_RETURNS: dict[str, list[float]] = _make_sample_returns()
SAMPLE_NAMES = {
    "510300": "沪深300ETF",
    "511010": "国债ETF",
    "518880": "黄金ETF",
    "513100": "纳指ETF",
}


@contextmanager
def _bypass_proxy():
    """临时清掉代理环境变量再恢复。

    akshare 的数据源（东方财富/新浪等）都是国内站，走科学上网代理（如 Clash
    127.0.0.1:7897）反而连不上。这里在请求期间临时移除 *_PROXY，请求完再还原，
    不影响 agent 与 LLM 端点的通信。可设 FIN_AKSHARE_USE_PROXY=1 关闭此行为。"""
    if os.environ.get("FIN_AKSHARE_USE_PROXY"):
        yield
        return
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _fetch_via_akshare(symbol: str, days: int) -> list[float] | str:
    """尝试用 akshare 取真实日线收益。

    成功返回 list[float]；失败返回一段简短的失败原因字符串（供降级时透明展示，
    方便在真实终端里判断是 没装/代理/网络 哪种问题）。"""
    try:
        import akshare as ak  # 延迟导入：没装也不影响离线演示
    except Exception:
        return "未安装 akshare"

    try:
        with _bypass_proxy():
            df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
        if df is None or df.empty or "收盘" not in df.columns:
            return "返回数据为空或格式异常"
        closes = df["收盘"].astype(float).to_numpy()
        if len(closes) < 2:
            return "数据点不足"
        closes = closes[-(days + 1):]
        rets = np.diff(closes) / closes[:-1]
        return [round(float(x), 6) for x in rets]
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:60]}"


_ANN = (
    ToolAnnotations(readOnlyHint=True, openWorldHint=True)
    if ToolAnnotations is not None
    else None
)


@tool(
    "get_price_history",
    "获取某只 ETF/基金的历史日收益序列（A股代码，如 510300=沪深300ETF, "
    "511010=国债ETF, 518880=黄金ETF, 513100=纳指ETF）。返回日收益数组与年化统计，"
    "供组合分析/优化工具使用。",
    {"symbol": str, "days": int},
    annotations=_ANN,
)
async def get_price_history(args: dict) -> dict:
    symbol = str(args.get("symbol", "")).strip()
    days = int(args.get("days") or 250)

    if not symbol:
        return {
            "content": [{"type": "text", "text": "错误：必须提供 symbol（如 510300）。"}],
            "isError": True,
        }

    # 1) 真实数据优先 → 2) 已知 symbol 降级到示例数据(带失败原因) → 3) 明确报错
    fetched = _fetch_via_akshare(symbol, days)
    if isinstance(fetched, list):
        returns = fetched
        source = "akshare(实时)"
    else:  # 失败：fetched 是原因字符串
        if symbol in SAMPLE_RETURNS:
            returns = SAMPLE_RETURNS[symbol][-days:]
            source = f"内置示例数据(实时获取失败: {fetched})"
        else:
            known = ", ".join(f"{k}={v}" for k, v in SAMPLE_NAMES.items())
            return {
                "content": [{
                    "type": "text",
                    "text": (
                        f"无法获取 {symbol} 的实时数据（{fetched}），且该代码无离线样本。\n"
                        f"离线可用样本：{known}"
                    ),
                }],
                "isError": True,
            }

    arr = np.asarray(returns, dtype=float)
    ann_return = float(arr.mean() * 252)
    ann_vol = float(arr.std(ddof=1) * np.sqrt(252)) if len(arr) > 1 else 0.0

    payload = {
        "symbol": symbol,
        "name": SAMPLE_NAMES.get(symbol, symbol),
        "source": source,
        "n_days": len(arr),
        "annualized_return": round(ann_return, 4),
        "annualized_volatility": round(ann_vol, 4),
        "daily_returns": [round(x, 6) for x in arr.tolist()],
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
