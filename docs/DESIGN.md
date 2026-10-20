# Design

What was decided, and why.

## A separate application, using only the gateway's public API

The chat app is a client of the gateway, like any other product that would sit in front of
it. It uses `POST /v1/generate` (streamed), `GET /v1/tenants/{id}/usage`, `GET /v1/models`
and `GET /healthz`, and nothing else. It has no gateway code and no knowledge of how the
gateway routes, meters or schedules. The gateway repository did not change for it.

## A backend between the browser and the gateway

The browser could not call the gateway directly, for two reasons:

- The gateway sends no CORS headers.
- `/v1/generate` takes one `prompt` string, with no list of messages, so something has to
  hold the conversation.

The chat backend (FastAPI) does both jobs. It keeps each conversation in memory, keyed by
the tenant and an id the browser picks, and relays the gateway's stream to the browser as server-sent
events: `start` (the model the gateway chose, from its `X-Model-Used` and
`X-Downgraded-From` headers), `token`, then `done` (the gateway's response, unchanged) or
`error`.

Every outcome is an event in a 200 stream, including a refusal that happens before the
gateway streams anything. `error` carries the gateway's own status and error body. This
gives the browser one code path, and the gateway's messages reach the user word for word.

## History in one prompt

`prompt.py` writes the system text, then the earlier turns as `User:` / `Assistant:` lines,
then the new message. The oldest exchange is dropped first, user turn and reply together,
until the prompt fits in `CHAT_HISTORY_CHARS`. With the gateway's `endpoint: chat` setting
the whole string reaches the model as one user message, so it is worded as an instruction
("Reply to the user's latest message") rather than as a transcript for the model to continue.

History belongs to a tenant. Switching tenant in the middle of a thread starts that tenant's
own history, and the page marks the point with a divider. The first version keyed history by
conversation id alone, so a tenant picked mid-thread saw the previous tenant's turns: a data
leak between customers, and it spoiled the side-by-side comparison (the 8B model answered
"you've already read them"). Testing against the real models caught it.

Only finished turns are remembered. A stopped or failed reply is not sent back as history.

## Stop

The stop button aborts the browser's fetch. The chat backend's stream generator is closed,
which closes its connection to the gateway. The gateway then cancels the request and closes
its connection to the model server, which frees the slot. Checked by hand with real models:
after a stopped reply, the gateway's `/v1/monitor/snapshot` showed the model with nothing
in flight and the request not counted as completed.

## Numbers shown

Every number on the page comes from the gateway's `done` payload or its per-token `t_ms`.
The page derives only the decode rate (completion tokens after the first, over the time
after the first) and the median gap between tokens (nearest-rank, as the gateway computes
percentiles), in pure functions in `frontend/src/state/derive.ts`. Costs are labelled as
the gateway's placeholder prices.

The page cannot tell whether the gateway is running real models or its simulated backend
(nothing in the API says so). The "About these numbers" note on the page covers both cases.

## Testing without a gateway or a model

`backend/tests/fake_gateway.py` mimics the gateway's API: same shapes, status codes, error
codes and demo tenants, plus a few switches in the prompt (slow, backend down, failure mid
reply). The backend unit tests and the Playwright smoke tests use it.

A fake can drift from the real thing. `test_contract.py` runs the same requests against a
real gateway and compares. The first run of it found a drift: the fake said
`model_not_allowed` where the gateway says `model_not_in_plan`. CI runs it against the
gateway's simulated backend, cloned from its public repository.

## Later: voice

`/api/chat` takes a text message and streams text back. A voice mode can wrap the same turn:
speech to text before it, text to speech on the streamed tokens after it. The chat flow
itself does not change.
