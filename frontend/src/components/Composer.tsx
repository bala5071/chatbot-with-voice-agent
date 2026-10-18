import { useState } from "react";

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
