from __future__ import annotations

from gateway_chat.prompt import Turn, build_prompt


def test_first_turn_is_system_then_message() -> None:
    assert build_prompt("Be brief.", [], "Hi there", 1000) == "Be brief.\n\nHi there"


def test_empty_system_is_left_out() -> None:
    assert build_prompt("  ", [], "Hi", 1000) == "Hi"


def test_history_is_written_before_the_new_message() -> None:
    history = [Turn("user", "What is 2+2?"), Turn("assistant", "4.")]
    assert build_prompt("Be brief.", history, "And 3+3?", 1000) == (
        "Be brief.\n\n"
        "Conversation so far:\nUser: What is 2+2?\nAssistant: 4.\n\n"
        "Reply to the user's latest message:\nAnd 3+3?"
    )


def test_oldest_exchange_is_dropped_first_and_whole() -> None:
    history = [
        Turn("user", "first question " * 5),
        Turn("assistant", "first answer " * 5),
        Turn("user", "second"),
        Turn("assistant", "two"),
    ]
    prompt = build_prompt("S", history, "third", 120)
    assert "first" not in prompt
    assert "User: second\nAssistant: two" in prompt
    assert len(prompt) <= 120


def test_system_and_message_survive_a_tiny_limit() -> None:
    history = [Turn("user", "old"), Turn("assistant", "reply")]
    assert build_prompt("System text", history, "the new message", 5) == (
        "System text\n\nthe new message"
    )
