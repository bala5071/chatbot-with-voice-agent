"""A stand-in for the gateway's HTTP API, for tests and the browser smoke tests.

It answers the endpoints this app uses with the same shapes and status codes as the real
gateway (Multi-Model-Inference-Gateway-Simulator, src/gateway/app.py), with the gateway's
three demo tenants and plans. No model runs: replies are fixed text, and every number in
them is made up. `tests/test_contract.py` checks the client against a real gateway.

Prompts can ask for a behaviour:
  [[slow]]          50 tokens, 200 ms apart (to test the stop button)
  [[backend-down]]  502 backend_unavailable before any token
  [[fail-mid]]      three tokens, then an error event

Serve it on its own with:  uv run uvicorn tests.fake_gateway:create_fake_gateway --factory
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

MODELS = ("economy", "standard", "premium")
PLANS: dict[str, tuple[str, ...]] = {
    "free": ("economy",),
    "pro": ("economy", "standard"),
    "enterprise": ("economy", "standard", "premium"),
}
TENANTS = {"initech": "free", "globex": "pro", "acme": "enterprise"}
BUDGET_TOKENS = 100_000


def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, **extra}}
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def create_fake_gateway() -> FastAPI:
    app = FastAPI()
    used: dict[str, int] = dict.fromkeys(TENANTS, 0)
    # Every /v1/generate body received, for tests to inspect.
    requests: list[dict[str, Any]] = []
    app.state.requests = requests

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "models": len(MODELS), "uptime_ms": 0.0}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"models": [{"id": m, "aliases": []} for m in MODELS]}

    @app.get("/v1/tenants/{tenant_id}/usage", response_model=None)
    async def usage(tenant_id: str) -> dict[str, Any] | JSONResponse:
        if tenant_id not in TENANTS:
            return _error(404, "unknown_tenant", f"Unknown tenant {tenant_id!r}.")
        plan = TENANTS[tenant_id]
        totals = {
            "requests": 0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "billed_tokens": used[tenant_id],
            "base_cost_usd": 0.0,
            "billed_cost_usd": 0.0,
        }
        return {
            "tenant_id": tenant_id,
            "plan": plan,
            "allowed_models": list(PLANS[plan]),
            "price_multiplier": 1.0,
            "period": {"start_ms": 0.0, "end_ms": 2_592_000_000.0},
            "budget_tokens": BUDGET_TOKENS,
            "used_tokens": used[tenant_id],
            "remaining_tokens": BUDGET_TOKENS - used[tenant_id],
            "total": totals,
            "by_model": {},
        }

    @app.post("/v1/generate", response_model=None)
    async def generate(request: Request) -> Response:
        body: dict[str, Any] = await request.json()
        requests.append(body)
        tenant_id = body.get("tenant_id")
        if tenant_id is None:
            return _error(
                401, "tenant_required", "This gateway needs a tenant_id on every request."
            )
        if tenant_id not in TENANTS:
            return _error(404, "unknown_tenant", f"Unknown tenant {tenant_id!r}.")
        allowed = PLANS[TENANTS[tenant_id]]
        if (body.get("model") is None) == (body.get("quality") is None):
            return _error(422, "invalid_request", "Give a model or a quality, not both.")
        if body.get("model") is not None:
            model = str(body["model"])
            if model not in allowed:
                plan = TENANTS[tenant_id]
                with_model = [name for name, models in PLANS.items() if model in models]
                return _error(
                    403,
                    "model_not_in_plan",
                    f"Tenant {tenant_id!r} is on the {plan!r} plan, which does not include "
                    f"model {model!r}. Models on this plan: {', '.join(allowed)}. "
                    f"Plans that include {model!r}: {', '.join(with_model)}.",
                    plan=plan,
                    requested_model=model,
                    allowed_models=list(allowed),
                    plans_with_model=with_model,
                )
        else:
            model = {"cheapest": allowed[0], "balanced": allowed[len(allowed) // 2]}.get(
                str(body["quality"]), allowed[-1]
            )
        prompt = str(body.get("prompt", ""))
        if "[[backend-down]]" in prompt:
            return _error(
                502,
                "backend_unavailable",
                f"Model backend {model!r} at http://127.0.0.1:11434: could not connect.",
                backend=model,
                url="http://127.0.0.1:11434",
            )

        slow = "[[slow]]" in prompt
        words = ["word"] * 50 if slow else f"Fake reply from {model}. No model ran here.".split()
        pieces = [w + " " for w in words[:-1]] + words[-1:]
        prompt_tokens = len(prompt.split())

        async def events() -> AsyncIterator[str]:
            for index, piece in enumerate(pieces):
                if slow:
                    await asyncio.sleep(0.2)
                if "[[fail-mid]]" in prompt and index == 3:
                    yield _sse(
                        "error", {"code": "backend_error", "message": "Connection lost mid-reply."}
                    )
                    return
                yield _sse("token", {"index": index, "token": piece, "t_ms": 10.0 + 5.0 * index})
            used[tenant_id] += prompt_tokens + len(pieces)
            reply = {
                "id": f"req-{len(requests)}",
                "text": "".join(pieces),
                "model": model,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "cached_tokens": 0,
                    "completion_tokens": len(pieces),
                    "total_tokens": prompt_tokens + len(pieces),
                },
                "timing": {
                    "queue_ms": 0.0,
                    "ttft_ms": 10.0,
                    "total_ms": 10.0 + 5.0 * (len(pieces) - 1),
                },
                "cost": {"usd": 0.0},
            }
            yield _sse("done", reply)

        headers = {"X-Model-Used": model, "Cache-Control": "no-cache"}
        return StreamingResponse(events(), media_type="text/event-stream", headers=headers)

    return app
