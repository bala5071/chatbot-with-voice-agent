"""Failures the caller hears about, each with a fixed sentence to speak.

The sentence is fixed text, never the gateway's message: that message could echo input, and
the caller should hear the same thing for the same kind of failure. ``str()`` of an error
names the type, the HTTP status and the gateway's error code, for logs; nothing else.
"""

from __future__ import annotations

from typing import ClassVar


class SpokenError(Exception):
    spoken: ClassVar[str] = "Sorry, something went wrong. Please call back later."

    def __init__(self, status: int | None = None, code: str | None = None) -> None:
        self.status = status
        self.code = code
        super().__init__(self._describe())

    def _describe(self) -> str:
        return f"{type(self).__name__}(status={self.status}, code={self.code})"

    def __str__(self) -> str:
        return self._describe()


class NotAuthorized(SpokenError):
    spoken = "I can't reach the clinic system right now. Please call back later."


class NotPermitted(SpokenError):
    spoken = "I'm not able to help with that from here. Please call back later."


class Busy(SpokenError):
    spoken = "We're very busy right now. Please try again in a minute."

    def __init__(
        self, status: int | None = None, code: str | None = None, retry_after_s: int | None = None
    ) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(status, code)


class Unavailable(SpokenError):
    spoken = "The clinic system is having trouble. Please call back later."


class TimedOut(SpokenError):
    spoken = "Sorry, that took too long. Please try again."


class Misconfigured(SpokenError):
    spoken = "Something is set up wrong on our side. Please call back later."


# The gateway's error codes, for an error that arrives inside a stream (its status is then
# 200 and cannot say what went wrong): each code stands for the status the gateway gives it
# when it can still answer with one. Anything not listed counts as a server error.
STREAM_CODE_STATUS: dict[str, int] = {
    "api_key_required": 401,
    "invalid_api_key": 401,
    "model_not_in_plan": 403,
    "rate_limited": 429,
    "budget_exhausted": 429,
    "queue_full": 429,
    "upstream_rate_limited": 429,
    "unknown_model": 404,
    "invalid_request": 422,
    "unsupported_field": 422,
}


def error_for_status(
    status: int, code: str | None = None, retry_after_s: int | None = None
) -> SpokenError:
    if status == 401:
        return NotAuthorized(status, code)
    if status == 403:
        return NotPermitted(status, code)
    if status == 429:
        return Busy(status, code, retry_after_s)
    if status >= 500:
        return Unavailable(status, code)
    return Misconfigured(status, code)


def error_for_stream_code(code: str | None) -> SpokenError:
    status = STREAM_CODE_STATUS.get(code or "", 500)
    error = error_for_status(status, code)
    error.status = None  # it came inside a 200 stream; the mapped status is not what was sent
    return error
