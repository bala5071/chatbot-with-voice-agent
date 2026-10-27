"""The client against answers recorded from the real gateway, and the recorder's own rules.

Fixtures are in ``tests/fixtures/gateway/``, written by ``scripts/record_fixtures.py`` (the
command and the gateway commit are inside each one). A case not recorded yet is skipped with
that reason; nothing here stands in for a recording.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from scripts.record_fixtures import (
    CASES,
    KEPT_HEADERS,
    OUT_DIR,
    RecordError,
    classify,
    fixture_text,
    gateway_commit,
    key_shaped,
    record,
    request_body,
)

from tests.helpers import BASE_URL, PLANTED_KEY, MockGateway, chunk, error_body, reply_events
from voice_agent.clock import FakeClock
from voice_agent.errors import Busy, NotAuthorized, SpokenError, error_for_stream_code
from voice_agent.gateway_client import GatewayClient, make_http_client
from voice_agent.interfaces import Message
from voice_agent.secret import Secret

FIXTURES = sorted(OUT_DIR.glob("*.json"))


def load(case: str) -> dict[str, Any]:
    path = OUT_DIR / f"{case}.json"
    if not path.exists():
        pytest.skip(f"{case}: not recorded yet (scripts/record_fixtures.py)")
    fixture: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return fixture


def replay_client(fixture: dict[str, Any]) -> GatewayClient:
    response = fixture["response"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            response["status"], headers=response["headers"], content=response["body"].encode()
        )

    return GatewayClient(
        make_http_client(BASE_URL, transport=httpx.MockTransport(handler)),
        Secret(PLANTED_KEY),
        FakeClock(),
        model=fixture["request"]["body"]["model"],
        max_tokens=fixture["request"]["body"]["max_tokens"],
        first_token_timeout_ms=1_000.0,
        total_timeout_ms=5_000.0,
    )


async def replay(fixture: dict[str, Any]) -> tuple[list[str], SpokenError | None]:
    deltas: list[str] = []
    try:
        async for delta in replay_client(fixture).stream(
            [Message("user", "replayed")], lambda: None
        ):
            deltas.append(delta)
    except SpokenError as exc:
        return deltas, exc
    return deltas, None


def data_events(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[5:])
        for line in body.splitlines()
        if line.startswith("data:") and line[5:].strip() != "[DONE]"
    ]


def content_of(body: str) -> str:
    return "".join(
        (c.get("delta") or {}).get("content") or ""
        for e in data_events(body)
        for c in e.get("choices") or []
    )


# --- the client against each recorded answer --------------------------------------------------


async def test_recorded_text_is_streamed_in_full() -> None:
    fixture = load("text")
    deltas, error = await replay(fixture)
    assert error is None
    assert "".join(deltas) == content_of(fixture["response"]["body"])
    assert "".join(deltas).strip()


async def test_recorded_tool_call_is_never_spoken() -> None:
    fixture = load("tool_call")
    deltas, error = await replay(fixture)
    assert error is None
    calls = [
        call
        for e in data_events(fixture["response"]["body"])
        for c in e.get("choices") or []
        for call in (c.get("delta") or {}).get("tool_calls") or []
    ]
    assert calls
    spoken = "".join(deltas)
    for call in calls:
        arguments = call.get("function", {}).get("arguments") or ""
        assert not arguments or arguments not in spoken


async def test_recorded_401_is_not_authorized() -> None:
    fixture = load("401")
    deltas, error = await replay(fixture)
    assert deltas == []
    assert isinstance(error, NotAuthorized)
    assert error.status == 401
    assert error.code == json.loads(fixture["response"]["body"])["error"]["code"]


async def test_recorded_429_is_busy_with_its_retry_after() -> None:
    fixture = load("429")
    deltas, error = await replay(fixture)
    assert deltas == []
    assert isinstance(error, Busy)
    assert error.status == 429
    retry = fixture["response"]["headers"].get("retry-after")
    assert error.retry_after_s == (int(retry) if retry and retry.isdigit() else None)


async def test_recorded_in_stream_error_keeps_the_output_and_maps_the_code() -> None:
    fixture = load("in_stream_error")
    deltas, error = await replay(fixture)
    code = next(
        e["error"]["code"] for e in data_events(fixture["response"]["body"]) if "error" in e
    )
    assert error is not None
    assert type(error) is type(error_for_stream_code(code))
    assert error.code == code
    assert "".join(deltas) == content_of(fixture["response"]["body"])


# --- what a fixture may hold ----------------------------------------------------------------


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_a_fixture_holds_no_key_and_only_the_kept_headers(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert key_shaped(text) == []
    fixture = json.loads(text)
    assert fixture["case"] == path.stem
    assert fixture["case"] in CASES
    assert set(fixture["response"]["headers"]) <= set(KEPT_HEADERS)
    assert set(fixture["request"]) == {"key_sent", "body"}
    assert fixture["request"]["key_sent"] is (fixture["case"] != "401")
    assert fixture["request"]["body"] == request_body(
        fixture["case"], fixture["request"]["body"]["model"]
    )
    assert len(fixture["gateway_commit"]) == 40
    assert fixture["command"].startswith("uv run python scripts/record_fixtures.py ")
    assert classify(fixture["response"]["status"], fixture["response"]["body"]) == path.stem


def test_the_key_scan_finds_a_planted_key() -> None:
    planted = json.dumps({"response": {"body": f'{{"echo": "{PLANTED_KEY}"}}'}})
    assert key_shaped(planted) == ["gateway api key"]
    assert key_shaped(f"Authorization: Bearer {'Zq7' * 8}") == ["bearer token"]
    assert key_shaped("Missing Authorization header; send a Bearer authentication token") == []


# --- the recorder ----------------------------------------------------------------------------


def http_for(gateway: MockGateway) -> httpx.AsyncClient:
    return make_http_client(BASE_URL, transport=gateway.transport())


async def test_the_recorder_keeps_only_the_listed_headers_and_no_request_headers() -> None:
    gateway = MockGateway(events=reply_events("We open at nine."))
    async with http_for(gateway) as http:
        got, sent = await record(http, "text", "standard", Secret(PLANTED_KEY), attempts=1)
    assert sent == 1
    assert gateway.requests[0].headers["authorization"]  # the key went to the gateway...
    text = fixture_text(got, Secret(PLANTED_KEY), "cmd", "0" * 40, BASE_URL)
    assert not Secret(PLANTED_KEY).found_in(text)  # ...and not into the fixture
    assert set(json.loads(text)["response"]["headers"]) == {"content-type"}
    assert classify(got.status, got.body) == "text"


async def test_the_401_case_sends_no_key() -> None:
    gateway = MockGateway(status=401, json_body=error_body("api_key_required"))
    async with http_for(gateway) as http:
        got, _ = await record(http, "401", "standard", Secret(PLANTED_KEY), attempts=1)
    assert "authorization" not in gateway.requests[0].headers
    assert got.key_sent is False
    assert classify(got.status, got.body) == "401"


async def test_a_fixture_that_echoes_the_key_is_refused_without_naming_it() -> None:
    gateway = MockGateway(status=401, json_body=error_body("invalid_api_key", PLANTED_KEY))
    async with http_for(gateway) as http:
        got, _ = await record(http, "text", "standard", Secret(PLANTED_KEY), attempts=1)
    with pytest.raises(RecordError) as caught:
        fixture_text(got, Secret(PLANTED_KEY), "cmd", "0" * 40, BASE_URL)
    assert "API key" in str(caught.value)
    assert PLANTED_KEY not in str(caught.value)


def test_a_fixture_with_another_key_shaped_value_is_refused() -> None:
    other = "gwk_" + "someoneElse" + "_" + "Ab9" * 6
    got = record_of(200, f"data: {json.dumps(error_body('x', other))}\n\n")
    with pytest.raises(RecordError) as caught:
        fixture_text(got, Secret(PLANTED_KEY), "cmd", "0" * 40, BASE_URL)
    assert "gateway api key" in str(caught.value)
    assert other not in str(caught.value)


async def test_the_429_case_stops_at_the_first_refusal() -> None:
    answers = iter([200, 200, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(answers)
        if status == 429:
            return httpx.Response(
                429, json=error_body("rate_limited"), headers={"retry-after": "7"}
            )
        return httpx.Response(200, content="".join(reply_events("ok")).encode())

    async with make_http_client(BASE_URL, transport=httpx.MockTransport(handler)) as http:
        got, sent = await record(http, "429", "standard", Secret(PLANTED_KEY), attempts=10)
    assert (got.status, sent, got.headers["retry-after"]) == (429, 3, "7")


def record_of(status: int, body: str) -> Any:
    from scripts.record_fixtures import Recorded

    return Recorded("text", request_body("text", "standard"), True, status, {}, body)


def tool_call_stream() -> str:
    function = {"name": "get_opening_hours", "arguments": '{"day": "Saturday"}'}
    call = {"index": 0, "id": "call_1", "type": "function", "function": function}
    body = json.loads(chunk(role=True)[6:])
    body["choices"][0]["delta"] = {"tool_calls": [call]}
    return chunk(role=True) + f"data: {json.dumps(body)}\n\n" + "data: [DONE]\n\n"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, "".join(reply_events("Hi.")), "text"),
        (200, tool_call_stream(), "tool_call"),
        (
            200,
            chunk(role=True) + chunk("a") + f"data: {json.dumps(error_body('x'))}\n\n",
            "in_stream_error",
        ),
        (401, json.dumps(error_body("invalid_api_key")), "401"),
        (429, json.dumps(error_body("rate_limited")), "429"),
        (200, chunk(role=True) + "data: [DONE]\n\n", None),  # no text: none of the cases
        (200, chunk(role=True) + chunk("cut off"), None),  # no [DONE]: none of the cases
        (500, json.dumps(error_body("internal_error")), None),
    ],
)
def test_classify_judges_from_what_came_back(status: int, body: str, expected: str | None) -> None:
    assert classify(status, body) == expected


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_the_gateway_commit_is_read_and_a_dirty_checkout_is_refused(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    git(tmp_path, "add", "f.txt")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "c")
    commit = gateway_commit(tmp_path)
    assert len(commit) == 40
    (tmp_path / "f.txt").write_text("two\n", encoding="utf-8")
    with pytest.raises(RecordError, match="local changes"):
        gateway_commit(tmp_path)
