from __future__ import annotations

from pathlib import Path

import httpx

from gateway_chat.app import create_app
from gateway_chat.config import Settings
from tests.helpers import Rig


def names(events: list[tuple[str, object]]) -> list[str]:
    return [name for name, _ in events]


async def test_a_turn_streams_start_tokens_done(rig: Rig) -> None:
    events = await rig.chat(message="Hello")
    assert names(events)[0] == "start"
    assert names(events)[-1] == "done"
    assert set(names(events)[1:-1]) == {"token"}
    start, done = events[0][1], events[-1][1]
    assert start["model"] == "premium"
    assert start["downgraded_from"] is None
    assert done["model"] == "premium"
    assert set(done) >= {"text", "usage", "timing", "cost"}


async def test_what_is_sent_to_the_gateway(rig: Rig) -> None:
    await rig.chat(message="Hello", quality="cheapest", allow_downgrade=True)
    [sent] = rig.gateway_requests
    assert sent["tenant_id"] == "acme"
    assert sent["quality"] == "cheapest"
    assert "model" not in sent
    assert sent["max_tokens"] == Settings().max_tokens
    assert sent["allow_downgrade"] is True
    assert sent["stream"] is True
    assert sent["prompt"].endswith("Hello")


async def test_history_goes_into_the_next_prompt(rig: Rig) -> None:
    first = await rig.chat(message="My name is Ada.")
    await rig.chat(message="What is my name?")
    await rig.chat(message="Unrelated", conversation_id="other")
    reply = first[-1][1]["text"]
    second, third = rig.gateway_requests[1]["prompt"], rig.gateway_requests[2]["prompt"]
    assert f"User: My name is Ada.\nAssistant: {reply}" in second
    assert second.endswith("What is my name?")
    assert "Ada" not in third


async def test_another_tenant_does_not_see_the_history(rig: Rig) -> None:
    """The same conversation id, switched to another tenant mid-thread."""
    await rig.chat(tenant_id="initech", message="My name is Ada.")
    await rig.chat(tenant_id="acme", message="What is my name?")
    await rig.chat(tenant_id="initech", message="And again?")
    _, acme, initech_again = (r["prompt"] for r in rig.gateway_requests)
    assert "Ada" not in acme
    assert "My name is Ada." in initech_again


async def test_a_failed_turn_is_not_remembered(rig: Rig) -> None:
    events = await rig.chat(message="[[fail-mid]]")
    assert names(events)[-1] == "error"
    await rig.chat(message="next")
    assert "fail-mid" not in rig.gateway_requests[1]["prompt"]


async def test_a_refusal_is_an_error_event_with_the_status(rig: Rig) -> None:
    events = await rig.chat(tenant_id="initech", quality=None, model="premium", message="hi")
    [(name, error)] = events
    assert name == "error"
    assert error["status"] == 403
    assert error["code"] == "model_not_in_plan"


async def test_backend_down_is_reported(rig: Rig) -> None:
    [(name, error)] = await rig.chat(message="[[backend-down]]")
    assert name == "error"
    assert error["status"] == 502
    assert error["code"] == "backend_unavailable"


async def test_bad_body_is_rejected_here(rig: Rig) -> None:
    response = await rig.http.post(
        "/api/chat", json={"tenant_id": "acme", "conversation_id": "a b", "message": "x"}
    )
    assert response.status_code == 422


async def test_tenants_lists_plans_and_usage(rig: Rig) -> None:
    await rig.chat(tenant_id="globex", message="hi")
    response = await rig.http.get("/api/tenants")
    assert response.status_code == 200
    found = {t["tenant_id"]: t for t in response.json()["tenants"]}
    assert list(found) == ["initech", "globex", "acme"]
    assert found["initech"]["usage"]["allowed_models"] == ["economy"]
    assert found["globex"]["usage"]["used_tokens"] > 0
    assert found["acme"]["usage"]["used_tokens"] == 0


async def test_an_unknown_tenant_in_the_list() -> None:
    rig = Rig(Settings(tenants=("acme", "nobody")))
    found = (await rig.http.get("/api/tenants")).json()["tenants"]
    await rig.close()
    assert found[1] == {
        "tenant_id": "nobody",
        "usage": None,
        "error": {"code": "unknown_tenant", "message": "Unknown tenant 'nobody'."},
    }


async def test_tenant_and_models_pass_through(rig: Rig) -> None:
    response = await rig.http.get("/api/tenants/nobody")
    assert response.status_code == 404
    models = (await rig.http.get("/api/models")).json()["models"]
    assert [m["id"] for m in models] == ["economy", "standard", "premium"]


async def test_health(rig: Rig) -> None:
    body = (await rig.http.get("/api/health")).json()
    assert body["gateway"]["reachable"] is True


async def test_gateway_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    gateway = httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url="http://gw")
    app = create_app(Settings(), http=gateway)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://chat"
    ) as http:
        health = (await http.get("/api/health")).json()
        tenants = await http.get("/api/tenants")
        chat = await http.post(
            "/api/chat",
            json={"tenant_id": "acme", "conversation_id": "c", "message": "x", "quality": "best"},
        )
    assert health["gateway"] == {"url": "http://gw", "reachable": False}
    assert tenants.status_code == 502
    assert tenants.json()["error"]["code"] == "gateway_unavailable"
    assert '"code": "gateway_unavailable"' in chat.text


async def test_forget_a_conversation(rig: Rig) -> None:
    await rig.chat(message="remember me")
    assert (await rig.http.delete("/api/conversations/c1")).status_code == 204
    await rig.chat(message="again")
    assert "remember me" not in rig.gateway_requests[1]["prompt"]


async def test_serves_the_built_frontend(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>chat</p>")
    rig = Rig(Settings(frontend_dir=tmp_path))
    page = await rig.http.get("/")
    api = await rig.http.get("/api/health")
    await rig.close()
    assert page.text == "<p>chat</p>"
    assert api.status_code == 200
