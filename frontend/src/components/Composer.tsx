import { useState } from "react";
import { MAX_MESSAGE_CHARS } from "../state/derive";

// Show how much room is left once a message gets this close to the limit.
const COUNT_FROM = MAX_MESSAGE_CHARS - 1000;

export function Composer(props: {
  busy: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || props.busy || props.disabled) return;
    props.onSend(trimmed);
    setText("");
  };

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        aria-label="Message"
        placeholder="Type a message. Enter sends, Shift+Enter starts a new line."
        rows={2}
        maxLength={MAX_MESSAGE_CHARS}
        aria-describedby={text.length >= COUNT_FROM ? "message-count" : undefined}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {text.length >= COUNT_FROM && (
        <span id="message-count" className="count muted">
          {text.length.toLocaleString("en-US")} / {MAX_MESSAGE_CHARS.toLocaleString("en-US")}
        </span>
      )}
      {props.busy ? (
        <button type="button" className="stop" onClick={props.onStop}>
          Stop
        </button>
      ) : (
        <button type="submit" disabled={props.disabled || !text.trim()}>
          Send
        </button>
      )}
    </form>
  );
}
