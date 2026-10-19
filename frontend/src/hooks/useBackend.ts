import { useCallback, useEffect, useState } from "react";
import { fetchHealth, fetchTenants } from "../api/client";
import type { Health, TenantEntry } from "../api/types";

export interface Tenants {
  entries: TenantEntry[] | null;
  error: string | null;
  refresh: () => void;
}

/** The configured tenants with their plans and usage, as the gateway reports them. */
export function useTenants(): Tenants {
  const [entries, setEntries] = useState<TenantEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetchTenants()
      .then((found) => {
        setEntries(found);
        setError(null);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
      });
  }, []);

  useEffect(refresh, [refresh]);
  return { entries, error, refresh };
}

const HEALTH_EVERY_MS = 10_000;

/** Whether the chat backend and the gateway behind it answer; checked every few seconds. */
export function useHealth(): Health | "down" | null {
  const [health, setHealth] = useState<Health | "down" | null>(null);

  useEffect(() => {
    let live = true;
    const check = () => {
      fetchHealth()
        .then((h) => {
          if (live) setHealth(h);
        })
        .catch(() => {
          if (live) setHealth("down");
        });
    };
    check();
    const timer = setInterval(check, HEALTH_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  return health;
}
