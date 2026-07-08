"""实时财经资讯工具（"感知的手"）——让判断能结合时效信息，而非只有静态知识库+历史数据。

═══════════════════════════════════════════════════════════════════════
对照源码：和 WebFetch/WebSearch 同类——拉外部时效信息→提炼→返回。
数据来自 akshare（财新要闻/新闻联播/东财个股新闻），照 macro.py 自动绕代理、失败如实降级。
═══════════════════════════════════════════════════════════════════════

边界：返回的是公开新闻标题与时间，供 agent 结合判断；不编造、取不到就说取不到。
"""

from __future__ import annotations

import json
from datetime import date

from .base import tool
from .market import _bypass_proxy  # 复用：国内数据源绕过 Clash 代理

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
except Exception:  # pragma: no cover
    _RO = None


def _find_col(df, keys: list[str]):
    """按关键词在列名里找一列（容忍 akshare 版本差异）。"""
    for c in df.columns:
        s = str(c)
        if any(k in s for k in keys):
            return c
    return None


def top_headlines(df, n: int = 10) -> list[dict]:
    """从 akshare 返回的新闻 DataFrame 里提炼 top N 条 {title, time, source}。"""
    if df is None or len(df) == 0:
        return []
    tcol = _find_col(df, ["标题", "title", "tag", "新闻"])
    timecol = _find_col(df, ["时间", "time", "date", "日期"])
    srccol = _find_col(df, ["来源", "source", "媒体"])
    out = []
    for _, r in df.head(n).iterrows():
        title = str(r[tcol]) if tcol is not None else str(r.iloc[0])
        t = str(r[timecol]) if timecol is not None else ""
        s = str(r[srccol]) if srccol is not None else ""
        title = " ".join(title.split())[:90]
        if title:
            out.append({"title": title, "time": t.strip()[:19], "source": s.strip()[:24]})
    return out


def fetch_news(query: str, scope: str) -> tuple[list[dict], str]:
    """返回（headlines, 来源标签）。失败抛异常，由 handler 统一降级。"""
    import akshare as ak

    q = (query or "").strip()
    sc = (scope or "").strip().lower()
    want_stock = bool(q) and (q.isdigit() or sc in ("stock", "个股", "标的", "symbol"))

    with _bypass_proxy():
        if want_stock:
            df = ak.stock_news_em(symbol=q)
            return top_headlines(df, 10), f"东方财富·{q}"
        # 市场/宏观要闻：先财新，失败再退新闻联播
        try:
            df = ak.stock_news_main_cx()
            return top_headlines(df, 10), "财新网要闻"
        except Exception:
            df = ak.news_cctv(date=date.today().strftime("%Y%m%d"))
            return top_headlines(df, 8), "新闻联播"


@tool(
    "get_news",
    "获取实时财经资讯。query 留空或填宽泛词=取市场/宏观要闻（财新/新闻联播）；"
    "query 填股票/ETF 代码（如 600519、510300）并把 scope 设为 stock=取该标的新闻。"
    "用于给宏观或个股判断补充时效信息——引用要注明标题、时间与来源，取不到就如实说明。",
    {"query": str, "scope": str},
    annotations=_RO,
    required=(),
)
async def get_news(args: dict) -> dict:
    query = str(args.get("query", ""))
    scope = str(args.get("scope", ""))
    try:
        import akshare  # noqa: F401
    except Exception:
        return {"content": [{"type": "text", "text": "未安装 akshare，无法获取资讯。"}],
                "isError": True}
    try:
        items, label = fetch_news(query, scope)
        if not items:
            return {"content": [{"type": "text",
                    "text": f"暂未取到「{query or '市场'}」相关资讯（来源 {label} 返回空）。"}],
                    "isError": True}
        payload = {
            "source": label,
            "as_of": str(date.today()),
            "count": len(items),
            "headlines": items,
            "note": "公开新闻标题，供结合判断；引用请注明标题/时间/来源，不构成投资建议。",
        }
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
    except Exception as e:
        return {"content": [{"type": "text",
                "text": f"获取资讯失败（{type(e).__name__}: {str(e)[:80]}）。"
                        f"可能是网络/代理/数据源变动，请稍后重试或在本地终端确认。"}],
                "isError": True}
