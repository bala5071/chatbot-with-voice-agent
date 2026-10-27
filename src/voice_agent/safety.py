"""The scripted paths: emergencies and requests for medical advice (CLAUDE.md, hard rule 9).

Both are checked on the transcript before any model call, the emergency check first. On a
match the agent says one fixed sentence and the model is never asked.

Recall first: a missed emergency is worse than a false alarm, whose cost is one scripted
sentence before the caller says their request again. So the transcript is normalized to
forgive how speech-to-text spells things (apostrophes dropped, ``9-1-1`` read as ``911``), and
besides the fixed phrases a few families catch wording a flat list would miss. It is a demo
safeguard, not a triage system: it sees only what the transcript says, and a mis-transcribed
emergency is a known gap (docs/threat-model.md).

The medical-advice guard works the same way (docs/05-medical-advice-guard.md), on dosage,
medication, diagnosis and treatment wording. It is keyword-based and will miss unusual
phrasing; then the model, which is told to give no advice, is the only safeguard left.
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


def _whole_words(phrases: tuple[str, ...], families: dict[str, str]) -> re.Pattern[str]:
    return re.compile(
        r"(?<![a-z0-9])(?:"
        + "|".join(
            [re.escape(p) for p in sorted(phrases, key=len, reverse=True)]
            + [f"(?:{family})" for family in families.values()]
        )
        + r")(?![a-z0-9])"
    )


_PATTERN = _whole_words(EMERGENCY_PHRASES, EMERGENCY_FAMILIES)


def is_emergency(transcript: str) -> bool:
    return _PATTERN.search(normalize(transcript)) is not None


# --- medical advice ---------------------------------------------------------------------------

MEDICAL_ADVICE_TEXT = (
    "I'm sorry, I can't give medical advice on this line, but one of our clinicians can. "
    "Would you like to book an appointment, or have a clinician call you back?"
)

# Normalized, as above. A false alarm costs one scripted sentence offering an appointment or a
# callback; a miss leaves only the system prompt between the caller and a generated answer. So,
# as with emergencies, when in doubt it triggers. "take" alone is not here: "can I take the
# 3pm slot" is a booking.
MEDICAL_PHRASES: tuple[str, ...] = (
    # dosage
    "dose",
    "doses",
    "dosage",
    "dosages",
    "dosing",
    "milligram",
    "milligrams",
    # medication
    "medication",
    "medications",
    "medicine",
    "medicines",
    "meds",
    "pill",
    "pills",
    "tablets",
    "capsule",
    "capsules",
    "prescription",
    "prescriptions",
    "prescribe",
    "prescribed",
    "drug",
    "drugs",
    "antibiotic",
    "antibiotics",
    "painkiller",
    "painkillers",
    "side effect",
    "side effects",
    "ibuprofen",
    "advil",
    "motrin",
    "acetaminophen",
    "paracetamol",
    "tylenol",
    "aspirin",
    "naproxen",
    "aleve",
    "amoxicillin",
    "penicillin",
    "antihistamine",
    "antihistamines",
    "benadryl",
    "insulin",
    "codeine",
    "steroid",
    "steroids",
    # diagnosis
    "diagnose",
    "diagnosed",
    "diagnosis",
    "symptom",
    "symptoms",
    "medical advice",
    "what is wrong with me",
    "whats wrong with me",
    "is it serious",
    "is this serious",
    "is that serious",
    "should i be worried",
    "should i worry",
    "is it contagious",
    "is this contagious",
    "is it infected",
    "is this infected",
    "is this normal",
    # treatment
    "treat",
    "treated",
    "treating",
    "treatment",
    "treatments",
    "cure",
    "remedy",
    "remedies",
    "get rid of",
    "heal",
)

# Who the question is about: "I", "my son", and so on.
_WHO = r"(?:i|we|he|she|they|you|my \w+)"
MEDICAL_FAMILIES: dict[str, str] = {
    # "how much ibuprofen should I take", "how many can I give my son"
    "how much to take": (
        rf"how (?:much|many)(?: \w+){{0,4}} (?:should|can|could|do|must|may|would) {_WHO}"
        r"(?: \w+)? (?:take|give|have|use)"
    ),
    "how often to take": (
        rf"how often(?: \w+){{0,3}} (?:should|can|do|must) {_WHO}(?: \w+)? (?:take|give|use)"
    ),
    "an amount": r"\d+ ?(?:mg|mgs|mcg|ml|mls|cc)",
    "safe to take": r"safe to (?:take|give|mix|combine|stop|double)",
    "taking": r"(?:stop|keep|start|still|been) taking",
    # "what can I take for a headache", "what should I give her to help"
    "what to take for": (
        rf"what (?:should|can|could|do) {_WHO} (?:take|give|use)(?: \w+)? (?:for|to help|against)"
    ),
    # "what should I do about my rash"
    "what to do about": (
        rf"what (?:should|can|do) {_WHO} do (?:about|for|with) (?:my|his|her|their|the|a|this|it)"
    ),
    # "could it be an infection", "might this be the flu"
    "could it be": (
        r"(?:could|might|can) (?:it|this|that) be (?:serious|cancer|an infection|infected|"
        r"contagious|broken|sprained|allergies|an allergy|the flu|covid|strep)"
    ),
    "do I need": (
        rf"(?:do|does) {_WHO} need (?:antibiotics|stitches|medicine|medication|an x ray|surgery)"
    ),
}

_MEDICAL_PATTERN = _whole_words(MEDICAL_PHRASES, MEDICAL_FAMILIES)


def is_medical_advice_request(transcript: str) -> bool:
    return _MEDICAL_PATTERN.search(normalize(transcript)) is not None
