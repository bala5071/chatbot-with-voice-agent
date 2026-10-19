import { useState } from "react";
import type { Health, Route } from "./api/types";
import { Composer } from "./components/Composer";
import { BudgetBar, DowngradeToggle, RoutePicker, TenantPicker } from "./components/Controls";
import { MessageList } from "./components/Messages";
import { useChat } from "./hooks/useChat";
import { useHealth, useTenants } from "./hooks/useBackend";
import { budgetView, knownModels } from "./state/derive";

function GatewayStatus(props: { health: Health | "down" | null }) {
  const { health } = props;
  if (health === null) return <span className="status">Checking…</span>;
  if (health === "down") {
    return <span className="status bad">Chat backend not reachable</span>;
  }
  return health.gateway.reachable ? (
    <span className="status good">Gateway at {health.gateway.url}</span>
  ) : (
    <span className="status bad">Gateway not reachable at {health.gateway.url}</span>
  );
}

export function App() {
  const tenants = useTenants();
  const health = useHealth();
  const chat = useChat(tenants.refresh);
  const [picked, setPicked] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>({ kind: "quality", quality: "best" });
  const [allowDowngrade, setAllowDowngrade] = useState(false);

  const entries = tenants.entries ?? [];
  const tenantId = picked ?? entries[0]?.tenant_id ?? null;
  const usage = entries.find((e) => e.tenant_id === tenantId)?.usage ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <h1>Gateway chat</h1>
        <GatewayStatus health={health} />
      </header>
      <div className="layout">
        <aside className="controls" aria-label="Settings">
          {tenants.error && (
            <div className="error" role="alert">
              <strong>Could not load tenants</strong>
              <span>{tenants.error}</span>
              <button type="button" onClick={tenants.refresh}>
                Retry
              </button>
            </div>
          )}
          {entries.length > 0 && tenantId && (
            <TenantPicker entries={entries} selected={tenantId} onSelect={setPicked} />
          )}
          <RoutePicker route={route} models={knownModels(entries)} onChange={setRoute} />
          <DowngradeToggle checked={allowDowngrade} onChange={setAllowDowngrade} />
          {usage && <BudgetBar view={budgetView(usage)} />}
          <button type="button" className="secondary" onClick={chat.reset}>
            New conversation
          </button>
          <section className="about" aria-label="About these numbers">
            <h2>About these numbers</h2>
            <p>
              Every number comes from the gateway's answer. With real models the model server
              (Ollama or llama-server) does the batching and caching; the gateway routes, enforces
              plans and budgets, meters and times. Times include the hop to the model server.
            </p>
            <p>
              *Costs use the gateway's placeholder prices, not real ones. If the gateway runs its
              simulated backend, replies are placeholder tokens and timings are simulated.
            </p>
          </section>
        </aside>
        <main className="chat">
          <MessageList messages={chat.state.messages} />
          <Composer
            busy={chat.state.busy}
            disabled={tenantId === null}
            onSend={(text) => {
              if (tenantId) chat.send(text, tenantId, route, allowDowngrade);
            }}
            onStop={chat.stop}
          />
        </main>
      </div>
    </div>
  );
}
