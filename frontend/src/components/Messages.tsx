import { Fragment, useEffect, useRef } from "react";
import type { AssistantMessage, Message } from "../state/chat";
import type { TurnStats as Stats } from "../state/derive";
import {
  errorHeadline,
  formatCount,
  formatMs,
  formatUsd,
  tenantSwitches,
  turnStats,
} from "../state/derive";

function TurnStats(props: { stats: Stats }) {
  const { stats } = props;
  const items: [string, string][] = [
    ["First token", formatMs(stats.ttftMs)],
    ["Total", formatMs(stats.totalMs)],
    [
      "Decode",
      stats.decodeTokensPerSecond === null
        ? "—"
        : `${stats.decodeTokensPerSecond.toFixed(1)} tok/s`,
    ],
    ["Gap p50", stats.itlP50Ms === null ? "—" : formatMs(stats.itlP50Ms)],
    [
      "Tokens",
      `${formatCount(stats.promptTokens)} in · ${formatCount(stats.completionTokens)} out`,
    ],
    ["Cost*", formatUsd(stats.costUsd)],
  ];
  return (
    <dl className="stats" aria-label="Reply statistics">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Reply(props: { message: AssistantMessage }) {
  const { message } = props;
  const stats = turnStats(message);
  return (
    <article
      className="message assistant"
      aria-label="Reply"
      aria-busy={message.status === "waiting" || message.status === "streaming"}
    >
      <header className="message-meta">
        {message.model ? (
          <span className="badge model" title="The model the gateway routed this turn to">
            {message.model}
          </span>
        ) : (
          message.status === "waiting" && <span className="muted">Waiting for the gateway…</span>
        )}
        {message.downgradedFrom && (
          <span className="badge warn">downgraded from {message.downgradedFrom}</span>
        )}
        <span className="muted">as {message.tenantId}</span>
      </header>
      {message.text && <div className="message-text">{message.text}</div>}
      {message.status === "streaming" && (
        <div className="muted">{formatCount(message.tokenTimes.length)} tokens so far…</div>
      )}
      {message.status === "stopped" && <div className="muted">Stopped.</div>}
      {message.error && (
        <div className="error" role="alert">
          <strong>{errorHeadline(message.error.code, message.error.status)}</strong>
          <span>{message.error.message}</span>
        </div>
      )}
      {stats && <TurnStats stats={stats} />}
    </article>
  );
}

export function MessageList(props: { messages: Message[] }) {
  const end = useRef<HTMLDivElement>(null);
  const last = props.messages.at(-1);
  const lastText = last?.text;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [props.messages.length, lastText]);

  if (props.messages.length === 0) {
    return (
      <div className="empty">
        <h2>Ask something</h2>
        <p>
          Every message goes through the gateway, which picks the model from the tenant's plan. Try
          the same question as <strong>initech</strong> (free plan, smallest model) and as{" "}
          <strong>acme</strong> with <em>Best</em> (largest model), and compare the answers and
          timings.
        </p>
      </div>
    );
  }
  const switches = tenantSwitches(props.messages);
  return (
    <div className="messages" aria-live="polite">
      {props.messages.map((message) =>
        message.role === "user" ? (
          <Fragment key={message.id}>
            {switches.has(message.id) && (
              <p className="tenant-switch" role="note">
                Now as <strong>{message.tenantId}</strong>, which has its own history: it does not
                see the turns above from other tenants.
              </p>
            )}
            <article className="message user" aria-label="You">
              <div className="message-text">{message.text}</div>
            </article>
          </Fragment>
        ) : (
          <Reply key={message.id} message={message} />
        ),
      )}
      <div ref={end} />
    </div>
  );
}
