"""Conversations held in memory, keyed by tenant and an id the browser picks."""

from __future__ import annotations

from collections import OrderedDict

from gateway_chat.prompt import Turn


class ConversationStore:
    """The turns of each conversation, least recently used dropped first past a limit.

    A conversation belongs to one tenant: the same conversation id under two tenants is two
    separate histories, so one tenant's turns never reach another tenant's prompt.

    Nothing is persisted: restarting the backend forgets every conversation.
    """

    def __init__(self, max_conversations: int) -> None:
        if max_conversations < 1:
            raise ValueError("max_conversations must be at least 1")
        self._max = max_conversations
        self._turns: OrderedDict[tuple[str, str], tuple[Turn, ...]] = OrderedDict()

    def history(self, tenant_id: str, conversation_id: str) -> tuple[Turn, ...]:
        key = (tenant_id, conversation_id)
        turns = self._turns.get(key, ())
        if key in self._turns:
            self._turns.move_to_end(key)
        return turns

    def append(self, tenant_id: str, conversation_id: str, *turns: Turn) -> None:
        key = (tenant_id, conversation_id)
        self._turns[key] = self._turns.get(key, ()) + turns
        self._turns.move_to_end(key)
        while len(self._turns) > self._max:
            self._turns.popitem(last=False)

    def forget(self, conversation_id: str) -> None:
        """Drop the conversation under every tenant."""
        for key in [k for k in self._turns if k[1] == conversation_id]:
            del self._turns[key]

    def __len__(self) -> int:
        return len(self._turns)
