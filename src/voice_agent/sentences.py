"""Cut a streamed reply into sentences, so each can be spoken as soon as it is complete.

A sentence ends at ``.``, ``!`` or ``?`` (with any closing quotes or brackets) followed by
white space, or at a line break. A full stop after a common abbreviation ("Dr.", "a.m.") or
a single letter does not end one. The rest is spoken by ``flush`` at the end of the stream.
"""

from __future__ import annotations

import re

ABBREVIATIONS = frozenset(
    {"dr", "mr", "mrs", "ms", "st", "ave", "rd", "vs", "etc", "e.g", "i.e", "a.m", "p.m"}
)
_END = re.compile(r"[.!?]+[\"')\]]*(?=\s)|\n+")


class SentenceSplitter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences: list[str] = []
        start = 0
        for match in _END.finditer(self._buffer):
            if match.group().startswith(".") and _is_abbreviation(
                self._buffer[start : match.start()]
            ):
                continue
            sentence = self._buffer[start : match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
        self._buffer = self._buffer[start:]
        return sentences

    def flush(self) -> str | None:
        rest, self._buffer = self._buffer.strip(), ""
        return rest or None


def _is_abbreviation(before: str) -> bool:
    words = before.split()
    if not words:
        return False
    last = words[-1].lower().lstrip("(\"'")
    return last in ABBREVIATIONS or (len(last) == 1 and last.isalpha())
