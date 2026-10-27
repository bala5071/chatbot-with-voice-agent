"""Record the real gateway's answers to fixed synthetic prompts, as test fixtures.

    export GATEWAY_API_KEY=...   # yourself; never printed
    uv run python scripts/record_fixtures.py --gateway-repo PATH [--case text --case 401 ...]

Cases: ``text``, ``tool_call`` and ``401`` by default; ``429`` and ``in_stream_error`` only
when named, because they cost budget:

- ``429`` sends one-token requests until the gateway answers 429, at most ``--attempts``;
- ``in_stream_error`` asks for a long answer and keeps it only if the stream really ends in an
  error event. The gateway has no switch for that (its timeouts are fixed), so it is produced
  only if something upstream fails while the answer streams.

A case is saved only if the gateway's answer really is that case (a 200 with no tool call is
not saved as ``tool_call``). Every fixture holds the request body (no headers; whether a key
was sent, as a boolean), the status, a fixed set of response headers, the raw body, the exact
command and the gateway's commit. That commit is read with git from ``--gateway-repo``, which
must have no local changes. Before writing, a fixture that contains the key, or anything shaped
like a key, is refused, naming only the kind of match.

The prompts are fixed, synthetic, and about the mock clinic (CLAUDE.md, hard rule 6).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from voice_agent.clinic import load_clinic, system_prompt
from voice_agent.config import ConfigError, Settings
from voice_agent.gateway_client import PATH, _auth_headers
from voice_agent.secret import Secret

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "tests" / "fixtures" / "gateway"
CASES = ("text", "tool_call", "401", "429", "in_stream_error")
DEFAULT_CASES = ("text", "tool_call", "401")
KEPT_HEADERS = ("content-type", "retry-after", "x-model-used", "x-provider", "x-provider-class")

QUESTION = "Hi, what time do you open on Saturday?"
TOOL = {
    "type": "function",
    "function": {
        "name": "get_opening_hours",
        "description": "The mock clinic's opening hours for one day of the week.",
        "parameters": {
            "type": "object",
            "properties": {"day": {"type": "string", "description": "A day of the week."}},
            "required": ["day"],
        },
    },
}
LONG_QUESTION = "Please describe, in as much detail as you can, everything the clinic offers."

# Names of key-shaped text; a match anywhere in a fixture refuses it.
KEY_SHAPES: dict[str, re.Pattern[str]] = {
    "gateway api key": re.compile(r"gwk_[A-Za-z0-9]+_[A-Za-z0-9_-]{8,}"),
    # A credential after "Bearer": 16 or more token characters including a digit, so a message
    # that only says "Bearer authentication" is not mistaken for one.
    "bearer token": re.compile(r"(?i)bearer\s+(?=[A-Za-z0-9._~+/-]*\d)[A-Za-z0-9._~+/-]{16,}"),
    "openai-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
}


class RecordError(Exception):
    pass


def key_shaped(text: str) -> list[str]:
    """The names of the key shapes found in ``text``; never the text itself."""
    return [name for name, pattern in KEY_SHAPES.items() if pattern.search(text)]


@dataclass(frozen=True, slots=True)
class Recorded:
    case: str
    request: dict[str, Any]
    key_sent: bool
    status: int
    headers: dict[str, str]
    body: str


def request_body(case: str, model: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt(load_clinic())},
            {"role": "user", "content": QUESTION},
        ],
        "max_tokens": 64,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if case == "tool_call":
        body["messages"][1]["content"] = QUESTION + " Use the get_opening_hours tool."
        body["tools"] = [TOOL]
        body["tool_choice"] = "auto"
    elif case == "429":
        body["max_tokens"] = 1
    elif case == "in_stream_error":
        body["messages"][1]["content"] = LONG_QUESTION
        body["max_tokens"] = 1024
    return body


def events(body: str) -> list[Any]:
    found = []
    for line in body.splitlines():
        data = line.removeprefix("data:").strip() if line.startswith("data:") else None
        if data and data != "[DONE]":
            try:
                found.append(json.loads(data))
            except ValueError:
                found.append(None)
    return found


def classify(status: int, body: str) -> str | None:
    """What the gateway's answer actually is, judged from what came back."""
    if status == 401:
        return "401"
    if status == 429:
        return "429"
    if status != 200:
        return None
    parsed = events(body)
    if any(isinstance(e, dict) and "error" in e for e in parsed):
        return "in_stream_error"
    deltas = [
        c.get("delta") or {}
        for e in parsed
        if isinstance(e, dict)
        for c in e.get("choices") or []
        if isinstance(c, dict)
    ]
    if any(d.get("tool_calls") for d in deltas):
        return "tool_call"
    done = any(line.strip() == "data: [DONE]" for line in body.splitlines())
    if done and any(d.get("content") for d in deltas):
        return "text"
    return None


async def send(
    http: httpx.AsyncClient, case: str, body: dict[str, Any], key: Secret | None
) -> Recorded:
    headers = _auth_headers(key) if key is not None else {}
    request = http.build_request("POST", PATH, json=body, headers=headers)
    response = await http.send(request, stream=True)
    try:
        raw = (await response.aread()).decode("utf-8", "replace")
    finally:
        await response.aclose()
    kept = {h: response.headers[h] for h in KEPT_HEADERS if h in response.headers}
    return Recorded(case, body, key is not None, response.status_code, kept, raw)


async def record(
    http: httpx.AsyncClient, case: str, model: str, key: Secret | None, attempts: int
) -> tuple[Recorded, int]:
    """The answer for ``case`` and how many requests it took."""
    body = request_body(case, model)
    if case == "401":
        return await send(http, case, body, None), 1
    if case != "429":
        return await send(http, case, body, key), 1
    for attempt in range(1, attempts + 1):
        got = await send(http, case, body, key)
        if got.status != 200:
            return got, attempt
    return got, attempts


def fixture_text(got: Recorded, key: Secret | None, command: str, commit: str, url: str) -> str:
    text = json.dumps(
        {
            "case": got.case,
            "command": command,
            "gateway_commit": commit,
            "gateway_url": url,
            "request": {"key_sent": got.key_sent, "body": got.request},
            "response": {"status": got.status, "headers": got.headers, "body": got.body},
        },
        indent=2,
        sort_keys=True,
    )
    if key is not None and key.found_in(text):
        raise RecordError(f"{got.case}: the fixture contains the API key; not written")
    shapes = key_shaped(text)
    if shapes:
        raise RecordError(f"{got.case}: the fixture contains {', '.join(shapes)}; not written")
    return text + "\n"


def gateway_commit(repo: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        commit = git("rev-parse", "HEAD")
        dirty = git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        raise RecordError(f"{repo} is not a git checkout") from None
    if dirty:
        raise RecordError(f"{repo} has local changes; record from a committed gateway")
    return commit


async def run(args: argparse.Namespace, settings: Settings, commit: str, command: str) -> int:
    key = settings.api_key
    if key is None and any(c != "401" for c in args.case):
        raise RecordError("GATEWAY_API_KEY is not set; only the 401 case can run without it")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    async with httpx.AsyncClient(
        base_url=settings.gateway_url,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0),
    ) as http:
        for case in args.case:
            got, sent = await record(http, case, settings.model, key, args.attempts)
            actual = classify(got.status, got.body)
            if actual != case:
                print(
                    f"{case}: not saved: the gateway answered {got.status}, "
                    f"which is {actual or 'none of the cases'} ({sent} request(s))"
                )
                continue
            path = args.out_dir / f"{case}.json"
            path.write_text(
                fixture_text(got, key, command, commit, settings.gateway_url),
                encoding="utf-8",
                newline="\n",
            )
            saved += 1
            print(f"{case}: saved {path.relative_to(ROOT).as_posix()} ({sent} request(s))")
    return 0 if saved == len(args.case) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gateway-repo", type=Path, required=True)
    p.add_argument("--case", action="append", choices=CASES)
    p.add_argument("--attempts", type=int, default=60, help="most requests for the 429 case")
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = p.parse_args(argv)
    args.case = args.case or list(DEFAULT_CASES)
    if args.attempts < 1:
        p.error("--attempts must be at least 1")
    command = " ".join(["uv run python scripts/record_fixtures.py", *(argv or sys.argv[1:])])
    try:
        settings = Settings.from_env(os.environ)
        commit = gateway_commit(args.gateway_repo)
        return asyncio.run(run(args, settings, commit, command))
    except (ConfigError, RecordError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"error: the gateway could not be reached ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
