"""Conversations held in memory, keyed by an id the browser picks."""

from __future__ import annotations

from collections import OrderedDict

from gateway_chat.prompt import Turn


class ConversationStore:
    """The turns of each conversation, least recently used dropped first past a limit.

    Nothing is persisted: restarting the backend forgets every conversation.
    """

    def __init__(self, max_conversations: int) -> None:
        if max_conversations < 1:
            raise ValueError("max_conversations must be at least 1")
        self._max = max_conversations
        self._turns: OrderedDict[str, tuple[Turn, ...]] = OrderedDict()

    def history(self, conversation_id: str) -> tuple[Turn, ...]:
        turns = self._turns.get(conversation_id, ())
        if conversation_id in self._turns:
            self._turns.move_to_end(conversation_id)
        return turns

    def append(self, conversation_id: str, *turns: Turn) -> None:
        self._turns[conversation_id] = self._turns.get(conversation_id, ()) + turns
        self._turns.move_to_end(conversation_id)
        while len(self._turns) > self._max:
            self._turns.popitem(last=False)

    def forget(self, conversation_id: str) -> None:
        self._turns.pop(conversation_id, None)

    def __len__(self) -> int:
        return len(self._turns)
