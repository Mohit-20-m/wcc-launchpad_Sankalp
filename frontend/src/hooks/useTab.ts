import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/** Console tab kept in the URL (?tab=...) so a refresh or a shared link
 *  lands on the same section. Unknown values fall back to the default. */
export function useTab(valid: readonly string[], fallback: string): [string, (tab: string) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const active = raw && valid.includes(raw) ? raw : fallback;
  const setTab = useCallback((tab: string) => setParams({ tab }), [setParams]);
  return [active, setTab];
}
