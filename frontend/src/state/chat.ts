import type { ChatEvent, GatewayError, Reply } from "../api/types";

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
  tenantId: string;
}

export type ReplyStatus = "waiting" | "streaming" | "done" | "stopped" | "error";

export interface AssistantMessage {
  id: string;
  role: "assistant";
  tenantId: string;
  status: ReplyStatus;
  text: string;
  model: string | null;
  downgradedFrom: string | null;
  /** When each token arrived, in ms since the gateway received the request. */
  tokenTimes: number[];
  reply: Reply | null;
  error: GatewayError | null;
}

export type Message = UserMessage | AssistantMessage;

export interface ChatState {
  conversationId: string;
  messages: Message[];
  /** A reply is on its way; only one at a time. */
  busy: boolean;
}

export type ChatAction =
  | { type: "send"; userId: string; replyId: string; text: string; tenantId: string }
  | { type: "event"; event: ChatEvent }
  | { type: "stopped" }
  | { type: "failed"; message: string }
  /** The stream closed; a reply still waiting then never got its end. */
  | { type: "ended" }
  | { type: "reset"; conversationId: string };

export function initialChat(conversationId: string): ChatState {
  return { conversationId, messages: [], busy: false };
}

function updateReply(
  state: ChatState,
  update: (reply: AssistantMessage) => AssistantMessage,
  busy: boolean,
): ChatState {
  const last = state.messages.at(-1);
  if (last?.role !== "assistant" || !state.busy) return state;
  return { ...state, busy, messages: [...state.messages.slice(0, -1), update(last)] };
}

function applyEvent(state: ChatState, event: ChatEvent): ChatState {
  switch (event.type) {
    case "start":
      return updateReply(
        state,
        (r) => ({
          ...r,
          status: "streaming",
          model: event.model,
          downgradedFrom: event.downgradedFrom,
        }),
        true,
      );
    case "token":
      return updateReply(
        state,
        (r) => ({
          ...r,
          status: "streaming",
          text: r.text + event.token,
          tokenTimes: [...r.tokenTimes, event.tMs],
        }),
        true,
      );
    case "done":
      return updateReply(
        state,
        (r) => ({
          ...r,
          status: "done",
          text: event.reply.text,
          model: event.reply.model,
          reply: event.reply,
        }),
        false,
      );
    case "error":
      return updateReply(state, (r) => ({ ...r, status: "error", error: event.error }), false);
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send":
      if (state.busy) return state;
      return {
        ...state,
        busy: true,
        messages: [
          ...state.messages,
          { id: action.userId, role: "user", text: action.text, tenantId: action.tenantId },
          {
            id: action.replyId,
            role: "assistant",
            tenantId: action.tenantId,
            status: "waiting",
            text: "",
            model: null,
            downgradedFrom: null,
            tokenTimes: [],
            reply: null,
            error: null,
          },
        ],
      };
    case "event":
      return applyEvent(state, action.event);
    case "stopped":
      return updateReply(state, (r) => ({ ...r, status: "stopped" }), false);
    case "failed":
      return updateReply(
        state,
        (r) => ({
          ...r,
          status: "error",
          error: { code: "network_error", message: action.message, status: null },
        }),
        false,
      );
    case "ended":
      return updateReply(
        state,
        (r) => ({
          ...r,
          status: "error",
          error: {
            code: "stream_ended",
            message: "The chat backend closed the stream before the reply was done.",
            status: null,
          },
        }),
        false,
      );
    case "reset":
      return initialChat(action.conversationId);
  }
}
