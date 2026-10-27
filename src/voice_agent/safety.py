"""The scripted emergency path (CLAUDE.md, hard rule 9).

Checked on the transcript before any model call. On a match the agent says one fixed
sentence and the model is never asked.

Recall first: a missed emergency is worse than a false alarm, whose cost is one scripted
sentence before the caller says their request again. So the transcript is normalized to
forgive how speech-to-text spells things (apostrophes dropped, ``9-1-1`` read as ``911``), and
besides the fixed phrases a few families catch wording a flat list would miss. It is a demo
safeguard, not a triage system: it sees only what the transcript says, and a mis-transcribed
emergency is a known gap (docs/threat-model.md).
"""

from __future__ import annotations

import re

EMERGENCY_TEXT = "If this is an emergency, hang up and call 911 now."

# Matched as whole words on the normalized transcript: lower case, letters, digits and single
# spaces, apostrophes dropped (so "can't" is "cant"). Written here in that form.
EMERGENCY_PHRASES: tuple[str, ...] = (
    "911",
    "nine one one",
    "nine eleven",
    "emergency",
    "ambulance",
    "heart attack",
    "choking",
    "unconscious",
    "passed out",
    "fainted",
    "unresponsive",
    "not responding",
    "stroke",
    "seizure",
    "convulsing",
    "overdose",
    "overdosed",
    "overdosing",
    "suicide",
    "suicidal",
    "kill myself",
    "end my life",
    "want to die",
    "hurt myself",
    "anaphylaxis",
    "anaphylactic",
    "allergic reaction",
    "throat is closing",
    "throat closing",
    "poisoned",
    "poisoning",
)

# Wording families, as regular expressions over the same normalized text. Each has examples in
# tests/test_units.py. ``(?: \w+){0,2}`` allows up to two words in between ("can barely
# breathe", "chest really hurts").
_BREATHING_BLOCKED = (
    r"cant|cannot|can not|couldnt|could not|unable to|barely|hard to|struggling to|trouble|"
    r"difficulty|hard time|short of|not|isnt|arent|wasnt|stopped|no longer|wont"
)
EMERGENCY_FAMILIES: dict[str, str] = {
    "breathing": rf"(?:{_BREATHING_BLOCKED})(?: \w+){{0,2}} breath(?:e|es|ed|ing)?",
    "chest pain": (
        r"chest(?: \w+){0,2} (?:pain|pains|hurts?|hurting|tight|tightness|pressure|aches?|aching)"
        r"|(?:pain|pains|pressure|tightness|ache) in (?:my|his|her|their|the|your|our) chest"
    ),
    "bleeding": r"bleed(?:s|ing)?|bled",
    "too many pills": (
        r"(?:too many|a lot of|lots of|a bottle of|a whole bottle of)(?: \w+)?"
        r" (?:pills|tablets|meds|medication|medicine)"
    ),
}

# 9-1-1, 9 1 1, 9.1.1, 9/11 -> 911. A colon is not a separator, so a time like 9:11 stays.
_NINE_ONE_ONE = re.compile(r"(?<![0-9:])9\s*[-./]?\s*1\s*[-./]?\s*1(?![0-9:])")
_APOSTROPHES = re.compile("['`\u2018\u2019]")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    text = _APOSTROPHES.sub("", text.lower())
    text = _NINE_ONE_ONE.sub(" 911 ", text)
    return _NON_WORD.sub(" ", text).strip()


_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(
        [re.escape(p) for p in sorted(EMERGENCY_PHRASES, key=len, reverse=True)]
        + [f"(?:{family})" for family in EMERGENCY_FAMILIES.values()]
    )
    + r")(?![a-z0-9])"
)


def is_emergency(transcript: str) -> bool:
    return _PATTERN.search(normalize(transcript)) is not None
