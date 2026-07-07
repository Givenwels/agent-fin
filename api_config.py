"""API setup helpers for the local financial agent.

The default path is Codex/OpenAI: OPENAI_API_KEY + OPENAI_MODEL through the
OpenAI SDK. Anthropic-compatible endpoints are still supported for legacy use.
"""

from __future__ import annotations

import asyncio
import getpass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
DEFAULT_CODEX_MODEL = "gpt-5.1"


def mask_secret(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return "未配置"
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}****{s[-4:]}"


def _read_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def write_env_values(values: dict[str, str], path: Path = ENV_FILE) -> None:
    """Upsert env values while preserving unrelated lines/comments."""
    existing = _read_env_lines(path)
    keys = set(values)
    out: list[str] = []
    seen: set[str] = set()
    for line in existing:
        if "=" not in line or line.lstrip().startswith("#"):
            out.append(line)
            continue
        k = line.split("=", 1)[0].strip()
        if k in keys:
            v = values[k]
            if v != "":
                out.append(f"{k}={v}")
            seen.add(k)
        else:
            out.append(line)
    if out and out[-1].strip():
        out.append("")
    for k, v in values.items():
        if k not in seen and v != "":
            out.append(f"{k}={v}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def current_api_status(env: dict | None = None) -> dict:
    if env is None:
        env = os.environ
    provider = (env.get("FIN_API_PROVIDER") or "").strip().lower()
    if not provider:
        provider = "codex"
    if provider in ("codex", "openai"):
        key = env.get("OPENAI_API_KEY") or env.get("CODEX_API_KEY") or ""
        return {
            "provider": "codex",
            "configured": bool(key),
            "model": env.get("OPENAI_MODEL") or env.get("CODEX_MODEL") or DEFAULT_CODEX_MODEL,
            "base_url": env.get("OPENAI_BASE_URL") or env.get("CODEX_BASE_URL") or "OpenAI default",
            "key": mask_secret(key),
        }
    key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY") or ""
    return {
        "provider": "anthropic",
        "configured": bool(key),
        "model": env.get("ANTHROPIC_MODEL") or "claude-3-5-sonnet-latest",
        "base_url": env.get("ANTHROPIC_BASE_URL") or "Anthropic default",
        "key": mask_secret(key),
    }


def render_api_status(env: dict | None = None) -> str:
    s = current_api_status(env)
    ok = "已配置" if s["configured"] else "未配置"
    return (
        f"API 状态：{ok}\n"
        f"  provider: {s['provider']}\n"
        f"  model:    {s['model']}\n"
        f"  base_url: {s['base_url']}\n"
        f"  key:      {s['key']}"
    )


def setup_codex_api_interactive(path: Path = ENV_FILE) -> None:
    """Interactive setup for Codex/OpenAI API credentials."""
    print("将接入 Codex/OpenAI API（OpenAI SDK）。密钥只写入本地 .env，不会入库。")
    print("需要一个 OpenAI API key；如果你用兼容网关，也可以填写 OPENAI_BASE_URL。")
    base = input("OPENAI_BASE_URL（回车=OpenAI 默认）> ").strip()
    model = input(f"OPENAI_MODEL（回车={DEFAULT_CODEX_MODEL}）> ").strip() or DEFAULT_CODEX_MODEL
    key = getpass.getpass("OPENAI_API_KEY（输入时不回显）> ").strip()
    if not key:
        print("未输入 key，已取消。")
        return
    values = {
        "FIN_API_PROVIDER": "codex",
        "OPENAI_MODEL": model,
        "OPENAI_API_KEY": key,
    }
    if base:
        values["OPENAI_BASE_URL"] = base
    write_env_values(values, path)
    os.environ.update(values)
    print("已写入 .env：")
    print(render_api_status(os.environ))


async def test_api_connection() -> tuple[bool, str]:
    """Make a tiny request to verify the configured provider."""
    import engine

    status = current_api_status(os.environ)
    if not status["configured"]:
        return False, "API 尚未配置。请先运行：python main.py --setup-api"
    try:
        client = engine.build_client()
        messages = [{"role": "user", "content": "只回复：pong"}]
        chunks: list[str] = []
        await engine.run_turn(
            client,
            "你是连通性测试助手。只输出 pong。",
            messages,
            on_text=lambda t: chunks.append(t),
            max_tokens=32,
            tools_schema=[],
            tool_by_name={},
            allow_delegate=False,
            max_iters=1,
        )
        await client.close()
        text = "".join(chunks).strip()
        return True, f"API 测试成功：{text or '已收到模型响应'}"
    except Exception as e:
        return False, f"API 测试失败：{type(e).__name__}: {e}"


def run_test_api_sync() -> int:
    ok, msg = asyncio.run(test_api_connection())
    print(msg)
    return 0 if ok else 1
