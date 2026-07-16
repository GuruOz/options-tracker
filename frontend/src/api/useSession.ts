import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { SessionMap, SessionState } from "./types";
import { getJSON } from "./client";

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

/** Live per-user session state: seeded by REST, kept fresh over WebSocket.
 *
 * Keyed by gateway id, one entry per declared user. Each user's gateway
 * authenticates, pulls and disconnects independently of the others. */
export function useSession(): SessionMap {
  const [sessions, setSessions] = useState<SessionMap>({});
  const retry = useRef<number | undefined>(undefined);
  const queryClient = useQueryClient();

  useEffect(() => {
    let closed = false;

    getJSON<SessionMap>("/api/session")
      .then(setSessions)
      .catch(() => {});

    function connect() {
      const ws = new WebSocket(wsUrl());
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "sessions") {
            // Full snapshot, sent on connect.
            setSessions(msg.data as SessionMap);
          } else if (msg.type === "session" && msg.gateway_id) {
            // One user's state changed — leave the others untouched.
            setSessions((prev) => ({
              ...prev,
              [msg.gateway_id]: msg.data as SessionState,
            }));
          } else if (msg.type === "data" && msg.resource) {
            // A poll persisted new data — refetch the matching query. Keys are
            // ["resource", account], so a prefix match invalidates every
            // account's variant, including the combined view that includes it.
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
            if (msg.resource === "account") {
              // The switcher's per-user tiles read the accounts list.
              queryClient.invalidateQueries({ queryKey: ["accounts"] });
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

  return sessions;
}
