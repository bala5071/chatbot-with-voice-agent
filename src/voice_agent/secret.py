"""``Secret``: the gateway API key, redacted everywhere it could be printed.

``repr``, ``str`` and ``format`` give ``********``; it cannot be pickled or copied into a
dict of attributes. ``reveal()`` returns the value and is called in one place only, where the
``Authorization`` header is built (``gateway_client._auth_headers``; an AST test checks it).
``found_in(text)`` says whether some text contains the value, for leak checks (the fixture
recorder), without returning it.
"""

from __future__ import annotations

from typing import Any, NoReturn, final

REDACTED = "********"


@final
class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value:
            raise ValueError("a secret cannot be empty")
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        return str(object.__getattribute__(self, "_value"))

    def found_in(self, text: str) -> bool:
        """Whether ``text`` contains the value, for leak checks that must not reveal it."""
        return str(object.__getattribute__(self, "_value")) in text

    def __repr__(self) -> str:
        return f"Secret({REDACTED!r})"

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        return REDACTED

    def __setattr__(self, name: str, value: Any) -> NoReturn:
        raise AttributeError("Secret is immutable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("a Secret cannot be pickled")

    def __copy__(self) -> Secret:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Secret:
        return self
