"""The small pieces: clock, sentences, safety, clinic, config, timing, errors."""

from __future__ import annotations

import asyncio
import re

import pytest

from voice_agent.clinic import load_clinic, system_prompt
from voice_agent.clock import FakeClock
from voice_agent.config import DEFAULT_GATEWAY_URL, ConfigError, Settings, check_gateway_url
from voice_agent.errors import (
    Busy,
    Misconfigured,
    NotAuthorized,
    Unavailable,
    error_for_status,
    error_for_stream_code,
)
from voice_agent.safety import (
    EMERGENCY_FAMILIES,
    EMERGENCY_PHRASES,
    MEDICAL_FAMILIES,
    MEDICAL_PHRASES,
    is_emergency,
    is_medical_advice_request,
    normalize,
)
from voice_agent.sentences import SentenceSplitter
from voice_agent.timing import Stage, StageTimer

# --- clock -------------------------------------------------------------------------------


async def test_fake_clock_sleep_wakes_only_when_time_reaches_the_deadline() -> None:
    clock = FakeClock()
    task = asyncio.ensure_future(clock.sleep(100))
    await clock.wait_for_sleepers(1)
    clock.advance(99)
    await asyncio.wait({task}, timeout=0)
    assert not task.done()
    clock.advance(1)
    await task
    assert clock.now_ms() == 100


def test_fake_clock_refuses_to_go_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        FakeClock().advance(-1)


# --- sentences -----------------------------------------------------------------------------


def split(*deltas: str) -> list[str]:
    splitter = SentenceSplitter()
    out = [s for d in deltas for s in splitter.feed(d)]
    rest = splitter.flush()
    return [*out, rest] if rest else out


def test_sentences_end_at_punctuation_followed_by_space() -> None:
    assert split("Hi there. How", " can I help? ", "Bye!") == [
        "Hi there.",
        "How can I help?",
        "Bye!",
    ]


def test_a_sentence_is_not_cut_before_the_next_space_arrives() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("Hello.") == []
    assert splitter.feed(" Next") == ["Hello."]


def test_abbreviations_and_initials_do_not_end_a_sentence() -> None:
    assert split("Dr. Alex Example sees you at 8 a.m. on Monday. J. Doe too.") == [
        "Dr. Alex Example sees you at 8 a.m. on Monday.",
        "J. Doe too.",
    ]


def test_line_breaks_end_a_sentence() -> None:
    assert split("Hours\nMonday to Friday") == ["Hours", "Monday to Friday"]


# --- safety --------------------------------------------------------------------------------

# How a transcript might spell an emergency. The first eight are the variants asked for in
# step 2; each must trigger on its own, inside an ordinary sentence.
REQUESTED_VARIANTS = (
    "nine one one",
    "9-1-1",
    "can not breathe",
    "cant breathe",
    "chest pain",
    "overdose",
    "not breathing",
    "bleeding badly",
)


@pytest.mark.parametrize("variant", REQUESTED_VARIANTS)
def test_requested_transcript_variants_trigger(variant: str) -> None:
    assert is_emergency(f"Hello, um, {variant}, please help")


@pytest.mark.parametrize(
    "text",
    [
        "I have chest pain",
        "My son CAN'T BREATHE!",
        "my husband can\u2019t breathe",
        "she can barely breathe",
        "he's short of breath",
        "my chest really hurts",
        "there's pressure in my chest",
        "she is unconscious",
        "I think I took an overdose",
        "he took too many pills",
        "she swallowed a whole bottle of sleeping pills",
        "Call 911",
        "call 9 1 1",
        "call 9.1.1 now",
        "Call nine-one-one!",
        "this is an emergency",
        "I want to kill myself",
        "he's bleeding heavily",
        "it won't stop bleeding",
        "my throat is closing",
    ],
)
def test_emergencies_are_detected(text: str) -> None:
    assert is_emergency(text)


@pytest.mark.parametrize(
    "text",
    [
        "What are your hours on Saturday?",
        "I'd like to book a check-up for next week.",
        "Can I bring my breathing test results?",
        "Is Dr. Sample in on Monday?",
        "chestnut street parking",
        "9110 Example Lane",
        "Can I have the 9:11 slot on Tuesday?",
        "I need to reschedule my chest x-ray.",
        "Can I get a refill of my inhaler prescription?",
        "Do you take new patients?",
        "My phone number is 555-0199.",
    ],
)
def test_ordinary_requests_are_not_emergencies(text: str) -> None:
    assert not is_emergency(text)


def test_every_phrase_triggers_on_its_own() -> None:
    assert all(is_emergency(f"well, {p}, please") for p in EMERGENCY_PHRASES)


FAMILY_EXAMPLES = {
    "breathing": "he could not catch his breath",
    "chest pain": "a tightness in her chest",
    "bleeding": "my daughter is bleeding",
    "too many pills": "he took lots of tablets",
}


def test_every_family_has_an_example_that_triggers() -> None:
    assert set(FAMILY_EXAMPLES) == set(EMERGENCY_FAMILIES)
    for example in FAMILY_EXAMPLES.values():
        assert is_emergency(example), example


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Can't BREATHE!", "cant breathe"),
        ("can\u2019t", "cant"),
        ("9-1-1", "911"),
        ("9 / 1 / 1", "911"),
        ("at 9:11", "at 9 11"),
        ("9110 Example Lane", "9110 example lane"),
    ],
)
def test_normalize_forgives_spelling(raw: str, normalized: str) -> None:
    assert normalize(raw) == normalized


# --- medical advice --------------------------------------------------------------------------

# The three asked for in step 4 must never trigger.
REQUESTED_NOT_MEDICAL = (
    "Do you take insurance?",
    "Can I take the 3pm slot?",
    "Is the clinic open on Saturday?",
)


@pytest.mark.parametrize("text", REQUESTED_NOT_MEDICAL)
def test_requested_ordinary_requests_are_not_medical_advice(text: str) -> None:
    assert not is_medical_advice_request(text)


@pytest.mark.parametrize(
    "text",
    [
        # dosage
        "What dose of ibuprofen should I take?",
        "How much Tylenol can I give my son?",
        "how many should I take",
        "How often should I take my antibiotics?",
        "Is 400mg too much?",
        "is 400 mg ok",
        "can I double my dose",
        "What's the dosage for children's Motrin?",
        # medication
        "Is it safe to take aspirin with my other pills?",
        "Should I stop taking it?",
        "What can I take for a headache?",
        "What should I give her to help with the fever?",
        "What are the side effects of amoxicillin?",
        "Can I give paracetamol to a two year old?",
        "What medication is best for allergies?",
        # diagnosis
        "Can you diagnose this over the phone?",
        "I have these symptoms, what is wrong with me?",
        "Could it be an infection?",
        "Might this be the flu?",
        "Should I be worried about this lump?",
        "Is it contagious?",
        "Do I need antibiotics?",
        "Does my daughter need stitches?",
        "I need some medical advice.",
        # treatment
        "What should I do about my rash?",
        "How do I treat a sprained ankle?",
        "Is there a cure for this?",
        "Any home remedies for a cough?",
        "How do I get rid of a sore throat?",
        # spelled the way a transcript might
        "WHAT DOSE SHOULD I TAKE",
        "what\u2019s the right dosage",
    ],
)
def test_medical_advice_requests_are_detected(text: str) -> None:
    assert is_medical_advice_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Hi, what time do you open on Saturday?",
        "Which services does the clinic offer?",
        "I'd like to book a check-up for next week.",
        "Do you take new patients?",
        "Can I take my son to his sports physical on Saturday?",
        "Is Dr. Sample in on Monday?",
        "Where are you located?",
        "Do you offer vaccinations?",
        "Can I reschedule my appointment to 3 pm?",
        "How much does a check-up cost?",
        "How many appointments are left this week?",
        "What should I bring to my appointment?",
        "Can I book a travel consultation?",
        "Is there parking at the clinic?",
        "Is it ok to come in early?",
        "Who is the nurse practitioner?",
        "Can I have the 9:11 slot on Tuesday?",
        "What should I do if I'm running late?",
        "How long does a check-up take?",
        "My phone number is 555-0199.",
    ],
)
def test_ordinary_requests_are_not_medical_advice(text: str) -> None:
    assert not is_medical_advice_request(text)


def test_every_medical_phrase_triggers_on_its_own() -> None:
    assert all(is_medical_advice_request(f"well, {p}, please") for p in MEDICAL_PHRASES)


MEDICAL_FAMILY_EXAMPLES = {
    "how much to take": "how much of it can my husband take",
    "how often to take": "how often should she take them",
    "an amount": "is 20 ml right",
    "safe to take": "is it safe to give both",
    "taking": "I have been taking it for a week",
    "what to take for": "what can we use for a burn",
    "what to do about": "what should I do about this cough",
    "could it be": "could this be strep",
    "do I need": "does he need an x-ray",
}


def test_every_medical_family_has_an_example_that_triggers() -> None:
    assert set(MEDICAL_FAMILY_EXAMPLES) == set(MEDICAL_FAMILIES)
    for example in MEDICAL_FAMILY_EXAMPLES.values():
        assert is_medical_advice_request(example), example


# Accepted on purpose (recall first): each gets the scripted sentence, which offers an
# appointment or a callback. Listed so the trade-off stays visible.
KNOWN_FALSE_ALARMS = (
    "Do you treat children?",
    "Can I get a refill of my inhaler prescription?",
    "I'd like an appointment about my symptoms.",
)


@pytest.mark.parametrize("text", KNOWN_FALSE_ALARMS)
def test_known_false_alarms_trigger(text: str) -> None:
    assert is_medical_advice_request(text)


# Known misses: keyword matching cannot see these (docs/threat-model.md). They go to the model,
# which is told to give no advice. If one starts to trigger, move it to the detected list.
KNOWN_MISSES = (
    "Is Calpol okay for a fever?",
    "Will a hot bath help my back?",
    "My ear has been ringing for a week, is that bad?",
)


@pytest.mark.parametrize("text", KNOWN_MISSES)
def test_known_misses_are_documented(text: str) -> None:
    assert not is_medical_advice_request(text)


# --- clinic: mock data only ------------------------------------------------------------------


def test_the_clinic_is_visibly_fake() -> None:
    clinic = load_clinic()
    assert "(mock)" in clinic.name
    assert re.fullmatch(r"555-01\d\d", clinic.phone)  # reserved for fiction
    assert clinic.website.endswith(".example.org")  # a reserved domain
    assert "Example" in clinic.address


def test_the_prompt_forbids_medical_advice() -> None:
    prompt = system_prompt(load_clinic())
    assert "Never give medical advice" in prompt
    assert "911" in prompt


# --- config ----------------------------------------------------------------------------------


def test_defaults() -> None:
    settings = Settings.from_env({})
    assert settings.gateway_url == DEFAULT_GATEWAY_URL
    assert settings.api_key is None
    assert settings.model == "standard"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000/",
        "http://[::1]:8000",
        "https://gateway.example.org",
    ],
)
def test_allowed_gateway_urls(url: str) -> None:
    assert check_gateway_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://192.168.1.10:8000", "plain http"),
        ("http://gateway.example.org", "plain http"),
        ("https://user:pw@gateway.example.org", "credentials"),
        ("ftp://127.0.0.1", "http"),
        ("https://gateway.example.org/?k=v", "query"),
        ("not a url", "http"),
    ],
)
def test_refused_gateway_urls(url: str, reason: str) -> None:
    with pytest.raises(ConfigError, match=reason):
        check_gateway_url(url)


def test_config_errors_name_the_variable_not_the_value() -> None:
    with pytest.raises(ConfigError) as caught:
        Settings.from_env({"VOICE_TOTAL_TIMEOUT_MS": "soon-ish-value"})
    assert "VOICE_TOTAL_TIMEOUT_MS" in str(caught.value)
    assert "soon-ish-value" not in str(caught.value)


# --- timing ----------------------------------------------------------------------------------


def test_stages_are_marked_once_and_missing_ones_are_none() -> None:
    clock = FakeClock(start_ms=5)
    timer = StageTimer(clock)
    timer.mark(Stage.SPEECH_END)
    clock.advance(10)
    timer.mark(Stage.TRANSCRIPT_READY)
    clock.advance(10)
    timer.mark(Stage.TRANSCRIPT_READY)
    times = timer.times()
    assert times[Stage.TRANSCRIPT_READY] == 10
    assert times[Stage.FIRST_TOKEN] is None


# --- errors ----------------------------------------------------------------------------------


def test_status_mapping() -> None:
    assert isinstance(error_for_status(401), NotAuthorized)
    assert isinstance(error_for_status(429, retry_after_s=3), Busy)
    assert isinstance(error_for_status(599), Unavailable)
    assert isinstance(error_for_status(418), Misconfigured)
    assert isinstance(error_for_stream_code(None), Unavailable)
