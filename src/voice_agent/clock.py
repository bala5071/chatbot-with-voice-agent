"""Time, injected. The only module allowed to read real time (CLAUDE.md, hard rule 1).

Times are milliseconds. ``WallClock`` is for the CLI and scripts; ``FakeClock`` is for tests:
its time moves only when ``advance`` is called, so a test states exactly how long each stage
took and gets exactly those numbers back.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> float:
        """Milliseconds on a monotonic clock; only differences mean anything."""
        ...

    async def sleep(self, ms: float) -> None: ...


class WallClock:
    def now_ms(self) -> float:
        return time.perf_counter() * 1000.0

    async def sleep(self, ms: float) -> None:
        await asyncio.sleep(max(0.0, ms) / 1000.0)


class FakeClock:
    """Time moves only through ``advance``. A ``sleep`` waits until time reaches its deadline.

    ``wait_for_sleepers(n)`` lets a test wait, without reading real time, until ``n`` tasks
    are asleep on this clock, so it can advance time at exactly the right point.
    """

    def __init__(self, start_ms: float = 0.0) -> None:
        self._now = start_ms
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []
        self._changed: asyncio.Event | None = None

    def now_ms(self) -> float:
        return self._now

    def advance(self, ms: float) -> None:
        if ms < 0:
            raise ValueError("time cannot go backwards")
        self._now += ms
        still = []
        for deadline, future in self._sleepers:
            if future.done():
                continue
            if deadline <= self._now:
                future.set_result(None)
            else:
                still.append((deadline, future))
        self._sleepers = still

    async def sleep(self, ms: float) -> None:
        if ms <= 0:
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._sleepers.append((self._now + ms, future))
        self._notify()
        await future

    @property
    def sleeping(self) -> int:
        return sum(1 for _, future in self._sleepers if not future.done())

    async def wait_for_sleepers(self, count: int) -> None:
        while self.sleeping < count:
            if self._changed is None:
                self._changed = asyncio.Event()
            await self._changed.wait()
            self._changed.clear()

    def _notify(self) -> None:
        if self._changed is not None:
            self._changed.set()
