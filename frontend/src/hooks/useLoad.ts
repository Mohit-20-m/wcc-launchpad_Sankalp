import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../lib/format";

interface Options {
  /** Re-fetch on this interval (ms). Used for "refreshes automatically" panels. */
  pollMs?: number;
  /** Skip fetching (e.g. until a tab is opened or an id is known). */
  enabled?: boolean;
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Tiny data-loading hook: fetch on mount / when deps change, expose
 *  loading + error state, optional polling. No cache library needed. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], options: Options = {}): Loaded<T> {
  const { pollMs, enabled = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [tick, setTick] = useState(0);
  const hasData = useRef(false);
  const depsKeyRef = useRef<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const depsKey = deps.map(String).join("|");

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let alive = true;

    // A different subject (another event, another team...) must never
    // briefly show the previous one's data, so drop it up front. A plain
    // refresh (tick / polling) keeps the current data on screen instead.
    if (depsKeyRef.current !== depsKey) {
      depsKeyRef.current = depsKey;
      hasData.current = false;
      setData(null);
      setError(null);
    }
    if (!hasData.current) setLoading(true);

    fnRef
      .current()
      .then((result) => {
        if (!alive) return;
        hasData.current = true;
        setData(result);
        setError(null);
      })
      .catch((err) => {
        if (!alive) return;
        setError(errorText(err, "Couldn't load this."));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [enabled, tick, depsKey]);

  useEffect(() => {
    if (!pollMs || !enabled) return;
    const id = setInterval(() => setTick((t) => t + 1), pollMs);
    return () => clearInterval(id);
  }, [pollMs, enabled]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
