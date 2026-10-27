"""Settings from the environment. Secrets come only from here (CLAUDE.md, hard rule 7).

- ``GATEWAY_URL``: the gateway, default ``http://127.0.0.1:8000``. Plain ``http`` is allowed
  only to a loopback host, because the API key travels in a header; anything else must be
  ``https``. A URL carrying a user name or password is refused.
- ``GATEWAY_API_KEY``: the application key, held as a ``Secret``.
- ``VOICE_MODEL``: the gateway model id the voice agent asks for, default ``standard``.
- ``VOICE_FIRST_TOKEN_TIMEOUT_MS``, ``VOICE_TOTAL_TIMEOUT_MS``, ``VOICE_MAX_TOKENS``.

Error messages name the variable, never its value.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from voice_agent.secret import Secret

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "standard"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    gateway_url: str
    api_key: Secret | None
    model: str = DEFAULT_MODEL
    first_token_timeout_ms: float = 15_000.0
    total_timeout_ms: float = 60_000.0
    max_tokens: int = 160

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        url = check_gateway_url(env.get("GATEWAY_URL", "").strip() or DEFAULT_GATEWAY_URL)
        raw_key = env.get("GATEWAY_API_KEY", "").strip()
        return cls(
            gateway_url=url,
            api_key=Secret(raw_key) if raw_key else None,
            model=env.get("VOICE_MODEL", "").strip() or DEFAULT_MODEL,
            first_token_timeout_ms=_positive(env, "VOICE_FIRST_TOKEN_TIMEOUT_MS", 15_000.0),
            total_timeout_ms=_positive(env, "VOICE_TOTAL_TIMEOUT_MS", 60_000.0),
            max_tokens=int(_positive(env, "VOICE_MAX_TOKENS", 160)),
        )

    def require_key(self) -> Secret:
        if self.api_key is None:
            raise ConfigError("GATEWAY_API_KEY is not set; export it in this terminal.")
        return self.api_key


def _positive(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if not value > 0:
        raise ConfigError(f"{name} must be positive")
    return value


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_gateway_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        _ = parts.port
    except ValueError:
        raise ConfigError("GATEWAY_URL is not a valid URL") from None
    if parts.scheme not in ("http", "https") or not host:
        raise ConfigError("GATEWAY_URL must be an http(s) URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ConfigError("GATEWAY_URL must not carry credentials; use GATEWAY_API_KEY")
    if parts.query or parts.fragment:
        raise ConfigError("GATEWAY_URL must not have a query or fragment")
    if parts.scheme == "http" and not is_loopback(host):
        raise ConfigError(
            "GATEWAY_URL uses plain http to a host that is not loopback; the API key would "
            "travel unencrypted. Use https."
        )
    return url.rstrip("/")
