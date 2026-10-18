from __future__ import annotations

from pathlib import Path

from gateway_chat.config import DEFAULT_TENANTS, Settings


def test_defaults_without_environment() -> None:
    settings = Settings.from_env({})
    assert settings == Settings()
    assert settings.tenants == DEFAULT_TENANTS
    assert settings.gateway_url == "http://127.0.0.1:8000"


def test_environment_overrides() -> None:
    settings = Settings.from_env(
        {
            "GATEWAY_URL": "http://gw:9000/",
            "CHAT_TENANTS": " acme, globex ,",
            "CHAT_MAX_TOKENS": "64",
            "CHAT_HISTORY_CHARS": "100",
            "CHAT_SYSTEM_PROMPT": "Be terse.",
            "CHAT_MAX_CONVERSATIONS": "3",
            "CHAT_FRONTEND_DIR": "/somewhere",
        }
    )
    assert settings.gateway_url == "http://gw:9000"
    assert settings.tenants == ("acme", "globex")
    assert settings.max_tokens == 64
    assert settings.history_chars == 100
    assert settings.system_prompt == "Be terse."
    assert settings.max_conversations == 3
    assert settings.frontend_dir == Path("/somewhere")
