"""报告导出 + 桌面推送（"伸出去的手"）——让 agent 能把成果落到文件、主动弹到你眼前。

═══════════════════════════════════════════════════════════════════════
两只手，都在合规内、无需任何密钥、不对外发送：
  · export_report      把复盘/告警/分析写成本地文件（portfolio/reports/）
  · push_notification  Windows 桌面通知（PowerShell toast，best-effort，失败静默）
邮件/微信等"对外发送"需要用户密钥且属权限敏感项，本模块不做（留作未来 env 钩子）。
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from .base import tool

try:
    from mcp.types import ToolAnnotations
    _RO = ToolAnnotations(readOnlyHint=True)
    _WRITE = ToolAnnotations(readOnlyHint=False)
except Exception:  # pragma: no cover
    _RO = _WRITE = None

REPORTS_DIR = Path(__file__).resolve().parent.parent / "portfolio" / "reports"


def _safe_name(name: str) -> str:
    """保留中文/字母/数字，其余替换成连字符，做文件名。"""
    cleaned = re.sub(r"[^\w一-鿿]+", "-", name.strip())
    return cleaned.strip("-")[:40] or "report"


def export_report_file(title: str, content: str, fmt: str = "md") -> Path:
    """把内容写成本地报告文件，返回路径。供 export_report 工具与 watch.py 复用。"""
    ext = "txt" if str(fmt).lower() == "txt" else "md"
    fname = f"{date.today()}-{datetime.now():%H%M%S}-{_safe_name(title)}.{ext}"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / fname
    path.write_text(content, encoding="utf-8")
    return path


# PowerShell：用现代 Windows toast（非阻塞）；标题/正文走环境变量避免引号注入。
_PS_TOAST = r"""
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
  $t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $x = $t.GetElementsByTagName('text')
  $x.Item(0).AppendChild($t.CreateTextNode($env:FIN_NOTIFY_TITLE)) | Out-Null
  $x.Item(1).AppendChild($t.CreateTextNode($env:FIN_NOTIFY_MSG)) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($t)
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('金融投研助手').Show($toast)
} catch { exit 1 }
"""


def notify(title: str, message: str) -> bool:
    """Windows 桌面通知。best-effort：非 Windows 或失败都返回 False，绝不抛异常。"""
    if sys.platform != "win32":
        return False
    try:
        env = dict(os.environ,
                   FIN_NOTIFY_TITLE=str(title)[:120],
                   FIN_NOTIFY_MSG=str(message)[:240])
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_TOAST],
            env=env, capture_output=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


@tool(
    "export_report",
    "把一段内容（复盘报告/风险告警/分析结论）导出成本地文件，返回文件路径。"
    "title=文件主题；content=正文（Markdown）；fmt 取 md 或 txt。用户说『导出/存成文件/保存这份报告』时调用。",
    {"title": str, "content": str, "fmt": str},
    annotations=_WRITE,
)
async def export_report(args: dict) -> dict:
    title = str(args.get("title", "report")).strip() or "report"
    content = str(args.get("content", ""))
    fmt = str(args.get("fmt", "md"))
    if not content.strip():
        return {"content": [{"type": "text", "text": "错误：content 不能为空。"}], "isError": True}
    try:
        path = export_report_file(title, content, fmt)
    except Exception as e:
        return {"content": [{"type": "text",
                "text": f"导出失败（{type(e).__name__}: {str(e)[:80]}）。"}], "isError": True}
    return {"content": [{"type": "text",
            "text": f"已导出报告到：{path}\n（在 portfolio/reports/ 下，可直接打开查看。）"}]}


@tool(
    "push_notification",
    "给用户发一条 Windows 桌面通知（主动提醒用，如风险触发、复盘已就绪）。"
    "title=标题；message=正文。best-effort：弹不出也不报错。不发邮件/不发外部消息。",
    {"title": str, "message": str},
    annotations=_RO,
)
async def push_notification(args: dict) -> dict:
    title = str(args.get("title", "金融投研助手")).strip() or "金融投研助手"
    message = str(args.get("message", "")).strip()
    if not message:
        return {"content": [{"type": "text", "text": "错误：message 不能为空。"}], "isError": True}
    ok = notify(title, message)
    tip = "已弹出桌面通知。" if ok else "已尝试推送（系统未弹出，可能是通知设置/非 Windows；不影响其它输出）。"
    return {"content": [{"type": "text", "text": tip}]}
