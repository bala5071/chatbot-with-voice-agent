import { useCallback, useReducer, useRef } from "react";
import { forgetConversation, streamChat } from "../api/client";
import type { ChatRequest, Route } from "../api/types";
import { chatReducer, initialChat, type ChatState } from "../state/chat";
import { newId } from "../state/derive";

export interface Chat {
  state: ChatState;
  send: (text: string, tenantId: string, route: Route, allowDowngrade: boolean) => void;
  stop: () => void;
  reset: () => void;
}

/** The conversation, and sending, stopping and forgetting it. `onSettled` runs after each turn. */
export function useChat(onSettled: () => void): Chat {
  const [state, dispatch] = useReducer(chatReducer, undefined, () => initialChat(newId("conv")));
  const inFlight = useRef<AbortController | null>(null);

  const send = useCallback(
    (text: string, tenantId: string, route: Route, allowDowngrade: boolean) => {
      if (inFlight.current) return;
      const controller = new AbortController();
      inFlight.current = controller;
      dispatch({ type: "send", userId: newId("msg"), replyId: newId("msg"), text, tenantId });
      const request: ChatRequest = {
        tenant_id: tenantId,
        conversation_id: state.conversationId,
        message: text,
        allow_downgrade: allowDowngrade,
        ...(route.kind === "quality" ? { quality: route.quality } : { model: route.model }),
      };
      streamChat(request, controller.signal, (event) => {
        dispatch({ type: "event", event });
      })
        .then(() => {
          dispatch({ type: "ended" });
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) dispatch({ type: "stopped" });
          else dispatch({ type: "failed", message: String(error) });
        })
        .finally(() => {
          inFlight.current = null;
          onSettled();
        });
    },
    [state.conversationId, onSettled],
  );

  const stop = useCallback(() => {
    inFlight.current?.abort();
  }, []);

  const reset = useCallback(() => {
    inFlight.current?.abort();
    void forgetConversation(state.conversationId);
    dispatch({ type: "reset", conversationId: newId("conv") });
  }, [state.conversationId]);

  return { state, send, stop, reset };
}
