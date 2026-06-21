import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { SessionState } from "./types";
import { getJSON } from "./client";

const INITIAL: SessionState = {
  status: "unknown",
  authenticated: false,
  connected: false,
  competing: false,
  account_id: null,
  message: "Connecting…",
  last_checked: null,
  user_logged_in: false,
  last_pull: null,
  pull_source: null,
  login_requested_at: null,
};

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

/** Live gateway/session state: seeded by REST, kept fresh over WebSocket. */
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>(INITIAL);
  const retry = useRef<number | undefined>(undefined);
  const queryClient = useQueryClient();

  useEffect(() => {
    let closed = false;

    getJSON<SessionState>("/api/session")
      .then(setState)
      .catch(() => {});

    function connect() {
      const ws = new WebSocket(wsUrl());
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "session") {
            setState(msg.data as SessionState);
          } else if (msg.type === "data" && msg.resource) {
            // A poll persisted new data — refetch the matching query.
            queryClient.invalidateQueries({ queryKey: [msg.resource] });
            // Derived views are recomputed server-side from these resources.
            if (msg.resource === "positions" || msg.resource === "market") {
              queryClient.invalidateQueries({ queryKey: ["alerts"] });
            }
            if (msg.resource === "market" || msg.resource === "signals") {
              // Composite-score sparklines read the persisted history series.
              queryClient.invalidateQueries({ queryKey: ["signal", "history"] });
            }
            if (msg.resource === "positions" || msg.resource === "trades") {
              queryClient.invalidateQueries({ queryKey: ["chains"] });
              // Income is derived from roll chains -> refresh it too.
              queryClient.invalidateQueries({ queryKey: ["income"] });
            }
            if (
              msg.resource === "positions" ||
              msg.resource === "market" ||
              msg.resource === "account"
            ) {
              queryClient.invalidateQueries({ queryKey: ["risk"] });
            }
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (!closed) retry.current = window.setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      closed = true;
      if (retry.current) window.clearTimeout(retry.current);
    };
  }, [queryClient]);

  return state;
}
