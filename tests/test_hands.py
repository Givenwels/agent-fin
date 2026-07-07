"""「手」相关回归测试：资讯提炼 / 报告导出 / 桌面推送容错。

只测纯逻辑与容错路径，不打真网络、不弹真通知（monkeypatch 隔离）。运行：pytest -q
"""

import asyncio

import pandas as pd

import tools.news as news
import tools.reporting as reporting


def _boom(*a, **k):
    raise RuntimeError("net down")


# ── 资讯提炼 ──────────────────────────────────────────────────────────
def test_top_headlines_extracts_columns():
    df = pd.DataFrame({
        "新闻标题": ["央行维持LPR不变", "A股震荡"],
        "发布时间": ["2026-06-28 09:00:00", "2026-06-28 10:00:00"],
        "文章来源": ["东方财富", "财新"],
    })
    out = news.top_headlines(df, 10)
    assert len(out) == 2
    assert out[0]["title"].startswith("央行")
    assert out[0]["time"].startswith("2026")
    assert out[0]["source"] == "东方财富"


def test_top_headlines_empty():
    assert news.top_headlines(None) == []
    assert news.top_headlines(pd.DataFrame()) == []


def test_get_news_degrades_on_error(monkeypatch):
    monkeypatch.setattr(news, "fetch_news", _boom)
    r = asyncio.run(news.get_news.handler({"query": "", "scope": ""}))
    assert r.get("isError")
    txt = r["content"][0]["text"]
    assert "失败" in txt or "未安装" in txt  # 降级而非崩溃


def test_get_news_success(monkeypatch):
    monkeypatch.setattr(news, "fetch_news",
                        lambda q, s: ([{"title": "x", "time": "t", "source": "s"}], "测试源"))
    r = asyncio.run(news.get_news.handler({"query": "", "scope": ""}))
    assert not r.get("isError")
    assert "测试源" in r["content"][0]["text"]


# ── 报告导出 ──────────────────────────────────────────────────────────
def test_export_report_file_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "REPORTS_DIR", tmp_path)
    p = reporting.export_report_file("周复盘 test", "# 标题\n正文内容", "md")
    assert p.exists() and p.suffix == ".md"
    assert "正文内容" in p.read_text(encoding="utf-8")


def test_export_report_tool_rejects_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(reporting, "REPORTS_DIR", tmp_path)
    r = asyncio.run(reporting.export_report.handler({"title": "x", "content": "   "}))
    assert r.get("isError")


def test_export_report_tool_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(reporting, "REPORTS_DIR", tmp_path)
    r = asyncio.run(reporting.export_report.handler(
        {"title": "复盘", "content": "正文", "fmt": "md"}))
    assert not r.get("isError")
    assert "已导出" in r["content"][0]["text"]
    assert list(tmp_path.glob("*.md"))  # 确实落盘


# ── 桌面推送容错（不真弹）──────────────────────────────────────────────
def test_notify_never_raises(monkeypatch):
    class _R:
        returncode = 0
    monkeypatch.setattr(reporting.subprocess, "run", lambda *a, **k: _R())
    assert reporting.notify("标题", "正文") in (True, False)


def test_push_notification_rejects_empty():
    r = asyncio.run(reporting.push_notification.handler({"title": "t", "message": ""}))
    assert r.get("isError")
