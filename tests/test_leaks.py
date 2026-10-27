"""The API key never leaks: a planted key goes through every client path, and every place it
could surface is scanned. The planted control proves the scanner finds a leak when there is
one, so a scanner that sees nothing cannot pass by accident."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback

import httpx
import pytest

from tests.helpers import (
    PLANTED_KEY,
    MockGateway,
    chunk,
    collect,
    error_body,
    find_leaks,
    make_client,
    reply_events,
)
from voice_agent.clock import FakeClock
from voice_agent.config import Settings
from voice_agent.errors import SpokenError
from voice_agent.secret import Secret

SCENARIOS = (
    "success",
    "401",
    "403",
    "429",
    "500",
    "503",
    "in-stream error",
    "connect error",
    "read timeout",
    "first-token timeout",
)


def gateway_for(name: str) -> MockGateway:
    if name == "success":
        return MockGateway(events=reply_events("Hi."))
    if name.isdigit():
        return MockGateway(
            status=int(name), json_body=error_body("x"), headers={"Retry-After": "1"}
        )
    if name == "in-stream error":
        return MockGateway(
            events=[chunk(role=True), chunk("a"), f"data: {json.dumps(error_body('x'))}\n\n"]
        )
    if name == "connect error":
        return MockGateway(raise_exc=httpx.ConnectError("refused"))
    if name == "read timeout":
        return MockGateway(raise_exc=httpx.ReadTimeout("slow"))
    return MockGateway(events=reply_events("Late."), hang_after=1)


async def run_scenario(name: str, places: list[tuple[str, str]]) -> None:
    clock = FakeClock()
    gateway = gateway_for(name)
    client = make_client(gateway, clock)
    places.append((f"{name}: repr(client)", repr(client)))
    task = asyncio.ensure_future(collect(client))
    if name == "first-token timeout":
        await gateway.hung.wait()
        await clock.wait_for_sleepers(1)
        clock.advance(10_000)
    try:
        await task
    except SpokenError as exc:
        places.append((f"{name}: str(error)", str(exc)))
        places.append((f"{name}: repr(error)", repr(exc)))
        places.append((f"{name}: error args", repr(exc.args)))
        places.append((f"{name}: traceback", "".join(traceback.format_exception(exc))))
        logging.getLogger("voice_agent").exception("turn failed")


@pytest.fixture
def everything_logged(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG)  # root: httpx, httpcore and ours, all at DEBUG
    for name in ("httpx", "httpcore", "voice_agent", "asyncio"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    return caplog


def log_places(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    return [
        (f"log record {i} ({r.name})", formatter.format(r)) for i, r in enumerate(caplog.records)
    ]


async def test_the_key_never_leaks(
    everything_logged: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    places: list[tuple[str, str]] = []
    for name in SCENARIOS:
        await run_scenario(name, places)

    secret = Secret(PLANTED_KEY)
    settings = Settings.from_env({"GATEWAY_API_KEY": PLANTED_KEY})
    places += [
        ("repr(secret)", repr(secret)),
        ("str(secret)", str(secret)),
        ("f-string", f"{secret} {secret!r} {secret:>40}"),
        ("percent format", "%s %r" % (secret, secret)),  # noqa: UP031
        ("repr(settings)", repr(settings)),
        ("str(settings)", str(settings)),
    ]
    captured = capsys.readouterr()
    places += [("stdout", captured.out), ("stderr", captured.err)]
    places += log_places(everything_logged)

    assert len(places) > 40  # every scenario contributed
    assert any(r.name.startswith("httpx") for r in everything_logged.records)  # httpx logged
    assert find_leaks(PLANTED_KEY, places) == []


async def test_planted_control_is_found(
    everything_logged: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    await run_scenario("401", [])
    logging.getLogger("voice_agent").debug("planted on purpose: %s", PLANTED_KEY)
    print("also planted on purpose:", PLANTED_KEY)
    captured = capsys.readouterr()
    places = [("stdout", captured.out), *log_places(everything_logged)]
    leaks = find_leaks(PLANTED_KEY, places)
    assert "stdout" in leaks
    assert any(name.startswith("log record") for name in leaks)


def test_secret_cannot_be_pickled_or_changed() -> None:
    import copy
    import pickle

    secret = Secret(PLANTED_KEY)
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    with pytest.raises(AttributeError):
        secret._value = "x"
    assert copy.deepcopy(secret) is secret
    assert not hasattr(secret, "__dict__")
    revealed_ok = secret.reveal() == PLANTED_KEY  # a boolean: a failure cannot print it
    assert revealed_ok
