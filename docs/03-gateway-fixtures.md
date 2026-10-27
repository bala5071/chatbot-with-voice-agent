# 03: The client against recorded answers from the real gateway

**Decided:** the client is tested against the gateway's real streamed answers, recorded once by
`scripts/record_fixtures.py`, in addition to the mock gateway.

**Why.** The mock gateway in `tests/helpers.py` follows the gateway's documented stream format
(its docs/31). A recording shows what the gateway actually sends: its headers, its chunk shapes,
its error bodies. If the gateway changes its format, the fix is a new recording, and the replay
tests then show what the client has to follow.

**What a fixture holds.** One JSON file per case in `tests/fixtures/gateway/`:
- the exact command;
- the gateway's commit, read with git from the gateway checkout, which must have no local
  changes;
- the request body, with no headers (whether a key was sent is a boolean);
- the status and a fixed set of response headers (`content-type`, `retry-after`,
  `x-model-used`, `x-provider`, `x-provider-class`);
- the raw body.

The prompts are fixed, synthetic, and about the mock clinic.

**Keys.** Before writing, the recorder refuses a fixture that contains the key (checked with
`Secret.found_in`, which never returns the value) or anything shaped like a key (a gateway key,
a bearer credential, an OpenAI-style key), naming only the kind of match. A test scans every
fixture again. Its control is a planted key, which the scan must find. The 401 case sends no
key at all.

**Honest cases.** A case is saved only if the answer really is that case. For example, a 200
with no tool call is not saved as `tool_call`.
- A tool call needs a tier served by a real model: the simulator's tiers have no tools.
- `429` sends one-token requests until the gateway refuses, at most `--attempts` of them, and
  each one costs budget.
- An error after output has started cannot be provoked on demand, because the gateway's chat
  timeouts are fixed (30 s to the first token, 120 s in total). The recorder keeps
  `in_stream_error` only if one really happened.

A case that has not been recorded is skipped in the tests with that reason, never faked.

**Replay.** Each recording goes through the real `GatewayClient` on an httpx mock transport:
- the text is streamed in full;
- a tool call's arguments are never spoken;
- 401 is `NotAuthorized` with the gateway's code;
- 429 is `Busy` with its `Retry-After`;
- an in-stream error keeps the text before it and maps by its code.
