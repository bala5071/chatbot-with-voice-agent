"""Settings, read once from the environment by the server entry point."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# The demo tenants in the gateway's packaged plans.yaml, one per plan.
DEFAULT_TENANTS = ("initech", "globex", "acme")

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer clearly and briefly. If you do not know something, say so."
)

# backend/src/gateway_chat/config.py -> the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class Settings:
    # Where the gateway listens.
    gateway_url: str = "http://127.0.0.1:8000"
    # Tenants offered in the tenant picker. The gateway decides what each may use.
    tenants: tuple[str, ...] = DEFAULT_TENANTS
    # Sent on every request: without it a model on a CPU can run past the gateway's timeout.
    max_tokens: int = 256
    # How much of the conversation is sent back with each turn, in characters.
    history_chars: int = 6000
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    # Conversations kept in memory; the least recently used is dropped past this.
    max_conversations: int = 200
    # The built frontend, served at / when it exists.
    frontend_dir: Path = _REPO_ROOT / "frontend" / "dist"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        default = cls()
        tenants = env.get("CHAT_TENANTS")
        return cls(
            gateway_url=env.get("GATEWAY_URL", default.gateway_url).rstrip("/"),
            tenants=(
                tuple(t.strip() for t in tenants.split(",") if t.strip())
                if tenants
                else default.tenants
            ),
            max_tokens=int(env.get("CHAT_MAX_TOKENS", default.max_tokens)),
            history_chars=int(env.get("CHAT_HISTORY_CHARS", default.history_chars)),
            system_prompt=env.get("CHAT_SYSTEM_PROMPT", default.system_prompt),
            max_conversations=int(env.get("CHAT_MAX_CONVERSATIONS", default.max_conversations)),
            frontend_dir=Path(env.get("CHAT_FRONTEND_DIR", str(default.frontend_dir))),
        )
