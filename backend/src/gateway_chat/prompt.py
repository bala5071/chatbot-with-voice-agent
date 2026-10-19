"""Turning a conversation into the one prompt string the gateway takes.

The gateway's /v1/generate has a single `prompt` field, not a list of messages, so the
history has to be written into the prompt. With the gateway's `endpoint: chat` setting the
whole string reaches the model as one user message, so it is phrased as an instruction about
an earlier conversation rather than as a raw transcript to be continued.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class Turn:
    role: Role
    text: str


def _render_turn(turn: Turn) -> str:
    speaker = "User" if turn.role == "user" else "Assistant"
    return f"{speaker}: {turn.text}"


def _render(system: str, history: Sequence[Turn], message: str) -> str:
    parts = [system.strip()] if system.strip() else []
    if history:
        parts.append("Conversation so far:\n" + "\n".join(_render_turn(t) for t in history))
        parts.append("Reply to the user's latest message:\n" + message)
    else:
        parts.append(message)
    return "\n\n".join(parts)


def build_prompt(system: str, history: Sequence[Turn], message: str, max_chars: int) -> str:
    """The prompt for `message`, with as much recent history as fits in `max_chars`.

    The oldest turns are dropped first, a user turn together with the reply to it, so the
    history never starts with an answer to a question that was cut. The system text and the
    new message are always kept, even when they alone are longer than `max_chars`.
    """
    kept = list(history)
    while kept and len(_render(system, kept, message)) > max_chars:
        del kept[0]
        if kept and kept[0].role == "assistant":
            del kept[0]
    return _render(system, kept, message)
