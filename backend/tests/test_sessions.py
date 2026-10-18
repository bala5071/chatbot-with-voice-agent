from __future__ import annotations

import pytest

from gateway_chat.prompt import Turn
from gateway_chat.sessions import ConversationStore


def test_turns_accumulate_per_conversation() -> None:
    store = ConversationStore(10)
    store.append("a", Turn("user", "hi"), Turn("assistant", "hello"))
    store.append("a", Turn("user", "bye"))
    store.append("b", Turn("user", "other"))
    assert [t.text for t in store.history("a")] == ["hi", "hello", "bye"]
    assert [t.text for t in store.history("b")] == ["other"]
    assert store.history("missing") == ()


def test_least_recently_used_is_dropped() -> None:
    store = ConversationStore(2)
    store.append("a", Turn("user", "1"))
    store.append("b", Turn("user", "2"))
    store.history("a")  # a is now the most recently used
    store.append("c", Turn("user", "3"))
    assert store.history("b") == ()
    assert store.history("a") != ()
    assert len(store) == 2


def test_forget() -> None:
    store = ConversationStore(2)
    store.append("a", Turn("user", "1"))
    store.forget("a")
    store.forget("never")
    assert store.history("a") == ()


def test_needs_room_for_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ConversationStore(0)
