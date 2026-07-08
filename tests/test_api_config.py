"""API setup/config tests.

These tests never call real model APIs and never require a real key.
"""

import asyncio
import sys

import pytest

import api_config
import engine


def test_mask_secret_hides_middle():
    assert api_config.mask_secret("") == "未配置"
    assert api_config.mask_secret("sk-1234567890abcd") == "sk-1****abcd"
    assert api_config.mask_secret("short") == "*****"


def test_write_env_values_preserves_comments_and_updates(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# hello\nOPENAI_MODEL=old\nOTHER=x\n", encoding="utf-8")
    api_config.write_env_values({
        "FIN_API_PROVIDER": "codex",
        "OPENAI_MODEL": "gpt-test",
        "OPENAI_API_KEY": "sk-test",
    }, env)
    text = env.read_text(encoding="utf-8")
    assert "# hello" in text
    assert "OTHER=x" in text
    assert "OPENAI_MODEL=gpt-test" in text
    assert "OPENAI_API_KEY=sk-test" in text
    assert "FIN_API_PROVIDER=codex" in text


def test_current_api_status_prefers_codex():
    status = api_config.current_api_status({
        "FIN_API_PROVIDER": "codex",
        "OPENAI_API_KEY": "sk-test-abcdef",
        "OPENAI_MODEL": "gpt-test",
    })
    assert status["provider"] == "codex"
    assert status["configured"] is True
    assert status["model"] == "gpt-test"
    assert "cdef" in status["key"]
    assert "sk-test-abcdef" not in api_config.render_api_status({
        "FIN_API_PROVIDER": "codex",
        "OPENAI_API_KEY": "sk-test-abcdef",
        "OPENAI_MODEL": "gpt-test",
    })


def test_current_api_status_defaults_to_codex():
    status = api_config.current_api_status({})
    assert status["provider"] == "codex"
    assert status["configured"] is False


def test_current_api_status_ignores_anthropic_without_explicit_provider():
    status = api_config.current_api_status({
        "ANTHROPIC_API_KEY": "sk-ant-old",
    })
    assert status["provider"] == "codex"
    assert status["configured"] is False


def test_current_api_status_allows_explicit_anthropic():
    status = api_config.current_api_status({
        "FIN_API_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-ant-old",
    })
    assert status["provider"] == "anthropic"
    assert status["configured"] is True


def test_claude_api_values_from_env_prefers_anthropic_env():
    values = api_config.claude_api_values_from_env({
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_MODEL": "deepseek-v4-flash",
    })

    assert values == {
        "FIN_API_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_MODEL": "deepseek-v4-flash",
    }


def test_claude_api_values_from_env_requires_key():
    values = api_config.claude_api_values_from_env({
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_MODEL": "deepseek-v4-flash",
    })

    assert values == {}


def test_engine_provider_name_codex(monkeypatch):
    monkeypatch.setenv("FIN_API_PROVIDER", "codex")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    assert engine.provider_name() == "codex"
    assert engine.model_name() == "gpt-test"


def test_engine_provider_defaults_to_codex_with_old_anthropic_env(monkeypatch):
    monkeypatch.delenv("FIN_API_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_API_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
    assert engine.provider_name() == "codex"


def test_engine_provider_allows_explicit_anthropic(monkeypatch):
    monkeypatch.setenv("FIN_API_PROVIDER", "anthropic")
    assert engine.provider_name() == "anthropic"


def test_openai_tool_schema_conversion():
    converted = engine._to_openai_tools([{
        "name": "x_tool",
        "description": "desc",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    }])
    assert converted == [{
        "type": "function",
        "function": {
            "name": "x_tool",
            "description": "desc",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        },
    }]


def test_main_test_api_does_not_nest_asyncio_run(monkeypatch, capsys):
    import main

    async def fake_test_api_connection():
        return True, "API ok"

    monkeypatch.setattr(api_config, "test_api_connection", fake_test_api_connection)
    monkeypatch.setattr(sys, "argv", ["main.py", "--test-api"])

    with pytest.raises(SystemExit) as exc:
        asyncio.run(main.main())

    assert exc.value.code == 0
    assert "API ok" in capsys.readouterr().out
