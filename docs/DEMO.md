# Demoing the gateway with the chatbot

A script for showing the [Multi-Model Inference Gateway](https://github.com/bala5071/Multi-Model-Inference-Gateway-Simulator)
working: real models through the chat, and the gateway's own scheduler in its simulated live
mode. It takes about ten minutes.

## Before you start

```powershell
.\scripts\demo.ps1 -LiveSim
```

This starts Ollama if needed, loads the models, starts the gateway on real models (port 8000),
the chat backend (8100) and the gateway's simulated live mode (8001), and opens three tabs:

| Tab | URL | What it is |
|---|---|---|
| Chat | <http://127.0.0.1:8100> | This app; every turn goes through the gateway on 8000 |
| Gateway dashboard | <http://127.0.0.1:8000/dashboard/> | The same gateway, watching the chat's requests |
| Simulated live | <http://127.0.0.1:8001/dashboard/> | A second gateway, no model, the scheduler on replayed load |

Stop everything with `.\scripts\demo.ps1 -Stop`.

**Switching tiers costs a model load.** On the laptop this was written on (RTX 4060, 8 GB),
Ollama cannot keep all three models on the GPU at once: the 8B model alone took 6.1 GB, and
Ollama kept only it loaded after the launcher loaded all three. So the first message after
switching to another tier waits for Ollama to load that model, which took a few seconds in
the one run that was timed. It shows up in "First token". Say so when it happens, or send
one throwaway message per tier just before you present.

## Part 1: real models through the gateway (chat)

The point: one API in front of three models, and the client's plan decides which model
answers.

1. **Plans pick the model.** Select **initech** (free plan), choose *Best*, and ask something
   ("Explain what a GPU does, in two sentences."). The badge says **economy**: *Best* within the
   free plan is the 1B model. Switch to **acme** (enterprise), *Best*, same question: **premium**,
   the 8B model. Compare the answers and the numbers under each one.
2. **The gateway enforces the plan.** As **initech**, open *Model choice* and pick **premium**.
   The gateway refuses with HTTP 403 `model_not_in_plan` and names the plans that include it.
   The chat app did not decide that; the gateway did.
3. **Metering.** The token budget bar drops after each turn. Those are the tenant's tokens
   as the gateway's ledger counted them, per 30-day period.
4. **Streaming and cancellation.** Ask for something long ("Write a 500-word essay on the
   history of compilers.") and press **Stop**. On the gateway dashboard the model's in-flight
   count goes back to 0: the gateway cancelled the request at the model server.
5. **Conversation.** Ask a follow-up ("Summarise that in one line."). The chat backend sends
   the earlier turns with it. The gateway itself is stateless per request.
6. **The gateway's view.** Switch to the gateway dashboard: requests per model and tenant,
   TTFT, inter-token latency and total latency for the turns you just sent. Queue, batch and
   KV-cache panels say *unavailable*, and that is correct: in this mode Ollama does the
   batching and caching, and the gateway cannot see inside it.

What to say about the numbers: they are real, measured by the gateway on this laptop, for a
handful of requests. They are not a benchmark. Costs are the gateway's placeholder prices.

## Part 2: the gateway's own scheduler (simulated live mode)

The point: what the gateway does when it schedules the models itself (continuous batching,
the prefix cache, SLO-aware downgrade). Real models through Ollama cannot show this, because
Ollama schedules them. Every tab on this dashboard has a banner saying it is simulated. Say
so too: no model runs, and nothing on it is a measurement.

1. **Overview.** The three model cards with queue, batch occupancy (out of 4 seats), KV use
   and prefix-cache hit rate, under the `steady` preset.
2. **Overload.** On the Playground tab choose the `overload` preset and press Restart. Back on
   the Overview, premium's queue fills, its batch is full (4 of 4) and it is marked
   *Degraded*.
3. **Downgrade.** On the Events tab, filter to downgrades: requests that allowed it were
   served by the standard model instead of waiting. In the chat, the *Allow a cheaper model*
   checkbox sends the same flag. It only takes effect when a model is missing its latency
   target, which you will rarely see with one person chatting.
4. **Determinism.** The banner shows the seed. The same seed replays the same events at any
   speed, which is how the gateway's CI performance gate tests the scheduler.

## Questions people ask

- *Why not show batching on the real models?* With an HTTP model server, the server batches.
  Our scheduler would need prefill and single decode steps exposed, which the HTTP API does
  not offer. The gateway's `docs/12-real-models.md` explains this.
- *Are the simulated numbers real?* The model timing profiles were calibrated on this
  laptop's Ollama runs (gateway `docs/13-calibration.md`), and several parameters are marked
  unstable there. Prices are placeholders.
- *What is next?* A voice mode on top of the same chat flow.
