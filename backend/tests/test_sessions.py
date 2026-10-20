from __future__ import annotations

import pytest

from gateway_chat.prompt import Turn
from gateway_chat.sessions import ConversationStore


def test_turns_accumulate_per_conversation() -> None:
    store = ConversationStore(10)
    store.append("t", "a", Turn("user", "hi"), Turn("assistant", "hello"))
    store.append("t", "a", Turn("user", "bye"))
    store.append("t", "b", Turn("user", "other"))
    assert [t.text for t in store.history("t", "a")] == ["hi", "hello", "bye"]
    assert [t.text for t in store.history("t", "b")] == ["other"]
    assert store.history("t", "missing") == ()


def test_tenants_do_not_share_a_conversation() -> None:
    store = ConversationStore(10)
    store.append("initech", "a", Turn("user", "secret"))
    assert store.history("acme", "a") == ()
    store.append("acme", "a", Turn("user", "mine"))
    assert [t.text for t in store.history("initech", "a")] == ["secret"]
    assert [t.text for t in store.history("acme", "a")] == ["mine"]


def test_least_recently_used_is_dropped() -> None:
    store = ConversationStore(2)
    store.append("t", "a", Turn("user", "1"))
    store.append("t", "b", Turn("user", "2"))
    store.history("t", "a")  # a is now the most recently used
    store.append("t", "c", Turn("user", "3"))
    assert store.history("t", "b") == ()
    assert store.history("t", "a") != ()
    assert len(store) == 2


def test_forget_drops_the_conversation_for_every_tenant() -> None:
    store = ConversationStore(5)
    store.append("initech", "a", Turn("user", "1"))
    store.append("acme", "a", Turn("user", "2"))
    store.append("acme", "b", Turn("user", "3"))
    store.forget("a")
    store.forget("never")
    assert store.history("initech", "a") == ()
    assert store.history("acme", "a") == ()
    assert store.history("acme", "b") != ()


def test_needs_room_for_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ConversationStore(0)
