"""核心纯逻辑回归测试。

只测不依赖网络/磁盘的纯函数（组合数学、看板、风险规则、快照对比、示例数据、持仓查找），
这些是改动时最容易回归的部分。运行：pytest -q
"""

import tempfile
import pathlib

import numpy as np

from tools.portfolio import _metrics, _align, _risk_parity, _max_sharpe_montecarlo, TRADING_DAYS
from tools.market import _make_sample_returns
from tools.holdings import compute_board, _summary, _find
from tools.risk import evaluate_risk
from tools.review import _compare
import tools.market as market


# ── 组合数学 ──────────────────────────────────────────────────────────
def test_metrics_annualization():
    daily = np.full(TRADING_DAYS, 0.001)  # 每日 +0.1%
    m = _metrics(daily)
    assert abs(m["annualized_return"] - 0.001 * TRADING_DAYS) < 1e-6
    assert m["annualized_volatility"] == 0.0  # 恒定收益无波动
    assert m["max_drawdown"] == 0.0           # 单调上涨无回撤


def test_align_truncates_to_min_length():
    valid, mat = _align(["A", "B"], {"A": [0.01, 0.02, 0.03], "B": [0.0, 0.01]})
    assert valid == ["A", "B"]
    assert mat.shape == (2, 2)  # 对齐到最短长度 2


def test_risk_parity_equal_contribution():
    # 对角协方差（不相关），风险平价应让各标的风险贡献相等
    cov = np.diag([0.04, 0.01, 0.09])  # sigma 0.2 / 0.1 / 0.3
    w = _risk_parity(cov)
    assert abs(w.sum() - 1.0) < 1e-6
    rc = w * (cov @ w)
    assert rc.max() - rc.min() < 1e-3      # 风险贡献近似相等
    assert w[1] > w[0] > w[2]              # 低波动权重更高（∝ 1/sigma）


def test_max_sharpe_weights_valid():
    mu = np.array([0.08, 0.03])
    cov = np.diag([0.04, 0.0016])
    w = _max_sharpe_montecarlo(mu, cov, n=2000)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= 0).all()                  # 长仓约束


def test_sample_returns_recentered_to_target():
    s = _make_sample_returns()
    assert set(s) >= {"510300", "511010", "518880", "513100"}
    ann = np.mean(s["510300"]) * TRADING_DAYS
    assert abs(ann - 0.08) < 0.01          # 重定标后年化≈设定的 8%


# ── 看板 ──────────────────────────────────────────────────────────────
def _items():
    return [
        {"name": "A股ETF", "asset_class": "股票/股票基金", "amount": 60000, "sector": "宽基", "cost": 50000},
        {"name": "科技ETF", "asset_class": "股票/股票基金", "amount": 20000, "sector": "科技"},
        {"name": "国债ETF", "asset_class": "债券/债基", "amount": 15000, "sector": ""},
        {"name": "货基", "asset_class": "现金/货基", "amount": 5000, "sector": ""},
    ]


def test_compute_board_breakdown():
    b = compute_board(_items())
    assert b["total"] == 100000
    cls = {c["class"]: c["pct"] for c in b["by_class"]}
    assert cls["股票/股票基金"] == 80.0
    assert b["cash_ratio"] == 5.0
    assert b["top_holding"]["name"] == "A股ETF" and b["top_holding"]["pct"] == 60.0
    assert b["pnl"]["return_pct"] == 20.0   # 仅有成本的 A股ETF：(60000-50000)/50000


def test_summary_and_find():
    items = _items()
    s = _summary(items)
    assert s["total"] == 100000
    assert _find(items, "国债ETF") == 2     # 按名称
    assert _find(items, "不存在") is None


# ── 风险规则 ──────────────────────────────────────────────────────────
def test_evaluate_risk_fires_on_concentration():
    concentrated = [
        {"name": "某科技股", "asset_class": "股票/股票基金", "amount": 90000, "sector": "科技"},
        {"name": "国债", "asset_class": "债券/债基", "amount": 10000, "sector": ""},
    ]
    warns = evaluate_risk(compute_board(concentrated))
    issues = {w["issue"] for w in warns}
    assert "单一资产占比过高" in issues
    assert "大类集中" in issues
    assert "行业集中度过高" in issues
    assert "现金比例过低" in issues


def test_evaluate_risk_clear_on_balanced():
    balanced = [
        {"name": "宽基", "asset_class": "股票/股票基金", "amount": 25000, "sector": "宽基"},
        {"name": "债基", "asset_class": "债券/债基", "amount": 25000, "sector": ""},
        {"name": "黄金", "asset_class": "商品(黄金等)", "amount": 25000, "sector": ""},
        {"name": "货基", "asset_class": "现金/货基", "amount": 25000, "sector": ""},
    ]
    warns = evaluate_risk(compute_board(balanced))
    assert warns == []                      # 均衡组合无告警


# ── 快照对比 ──────────────────────────────────────────────────────────
def test_compare_total_and_drift():
    cur = {"total": 100000, "by_class": [{"class": "股票/股票基金", "pct": 70.0},
                                         {"class": "债券/债基", "pct": 30.0}]}
    prev = {"date": "2026-06-01", "total": 80000,
            "by_class": {"股票/股票基金": 60.0, "债券/债基": 40.0}}
    c = _compare(cur, prev)
    assert c["total_change"] == 20000
    assert c["total_change_pct"] == 25.0
    assert c["class_drift_pct"]["股票/股票基金"] == 10.0
    assert c["class_drift_pct"]["债券/债基"] == -10.0


# ── 行情缓存（上下文控制）──────────────────────────────────────────────
def test_price_cache_roundtrip():
    tmp = pathlib.Path(tempfile.mkdtemp())
    market.PRICE_CACHE_DIR = tmp
    market.save_price_cache("510300", "沪深300ETF", "test", [0.01, -0.02, 0.03])
    c = market.load_price_cache("510300")
    assert c is not None
    assert c["name"] == "沪深300ETF"
    assert c["daily_returns"] == [0.01, -0.02, 0.03]
    assert market.load_price_cache("不存在") is None
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── 定时风险监控（主动型，纯规则）──────────────────────────────────────
def test_watch_flags_concentrated_and_clears_balanced():
    import shutil
    import watch
    import tools.holdings as holdings
    import tools.review as review

    tmp = pathlib.Path(tempfile.mkdtemp())
    holdings.HOLDINGS_FILE = tmp / "holdings.json"
    review.SNAP_DIR = tmp / "snapshots"
    watch.ALERT_DIR = tmp / "alerts"

    # 集中组合 → 应有风险提示 + 写出 latest.md
    holdings._save([
        {"name": "某股", "asset_class": "股票/股票基金", "amount": 95000, "sector": "科技"},
        {"name": "债", "asset_class": "债券/债基", "amount": 5000, "sector": ""},
    ])
    n = watch.run_watch()
    assert n >= 3
    assert (watch.ALERT_DIR / "latest.md").exists()

    # 均衡组合 → 无风险 + 清掉 latest.md
    holdings._save([
        {"name": "宽基", "asset_class": "股票/股票基金", "amount": 25000, "sector": "宽基"},
        {"name": "债", "asset_class": "债券/债基", "amount": 25000, "sector": ""},
        {"name": "金", "asset_class": "商品(黄金等)", "amount": 25000, "sector": ""},
        {"name": "货基", "asset_class": "现金/货基", "amount": 25000, "sector": ""},
    ])
    n2 = watch.run_watch()
    assert n2 == 0
    assert not (watch.ALERT_DIR / "latest.md").exists()
    shutil.rmtree(tmp, ignore_errors=True)
