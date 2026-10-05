/** An anonymous voter token for open-link voting, kept in this browser.
 *  It's a convenience for one-browser-one-voice, not a security boundary
 *  (see THREAT-MODEL.md: the server flags and rate-limits abuse). */
const KEY = "launchpad-voter-token";

export function getVoterToken(): string {
  try {
    let t = localStorage.getItem(KEY);
    if (!t || t.length < 16) {
      t = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem(KEY, t);
    }
    return t;
  } catch {
    // Storage blocked: fall back to a per-page-load token.
    return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
  }
}
