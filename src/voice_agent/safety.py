"""The scripted emergency path (CLAUDE.md, hard rule 9).

Checked on the transcript before any model call. On a match the agent says one fixed
sentence and the model is never asked. The phrase list is deliberately broad and certainly
incomplete: it is a demo safeguard, not a triage system, and the README says so.
"""

from __future__ import annotations

import re

EMERGENCY_TEXT = "If this is an emergency, hang up and call 911 now."

# Matched as whole words on the normalized transcript (lower case, letters, digits, spaces).
EMERGENCY_PHRASES: tuple[str, ...] = (
    "911",
    "nine one one",
    "emergency",
    "ambulance",
    "chest pain",
    "chest hurts",
    "heart attack",
    "can't breathe",
    "cannot breathe",
    "can not breathe",
    "trouble breathing",
    "not breathing",
    "stopped breathing",
    "choking",
    "unconscious",
    "passed out",
    "unresponsive",
    "stroke",
    "seizure",
    "overdose",
    "overdosed",
    "suicide",
    "suicidal",
    "kill myself",
    "end my life",
    "bleeding heavily",
    "won't stop bleeding",
    "severe bleeding",
    "anaphylaxis",
    "allergic reaction",
    "poisoned",
)

_NON_WORD = re.compile(r"[^a-z0-9' ]+")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.lower().replace("\u2019", "'")
    return _SPACES.sub(" ", _NON_WORD.sub(" ", text)).strip()


_PATTERN = re.compile(
    r"(?<![a-z0-9'])(?:"
    + "|".join(re.escape(p) for p in sorted(EMERGENCY_PHRASES, key=len, reverse=True))
    + r")(?![a-z0-9'])"
)


def is_emergency(transcript: str) -> bool:
    return _PATTERN.search(normalize(transcript)) is not None
