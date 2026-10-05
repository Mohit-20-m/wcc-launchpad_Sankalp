import { useState } from "react";
import { Download } from "lucide-react";
import { ShieldCheck } from "lucide-react";
import { api, downloadAuditCsv, type AuditVerify, type EventOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLive } from "../../../hooks/useLive";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtDateTime, truncate } from "../../../lib/format";

const FILTERS: [string, string][] = [
  ["", "Everything"],
  ["vote.", "Votes and abuse flags"],
  ["ballot.", "Ballot voids"],
  ["round.", "Rounds and deadlines"],
  ["submission.", "Submissions"],
  ["file.", "File uploads"],
  ["judge.", "Judge assignments and conflicts"],
  ["score.", "Scoring"],
  ["results.", "Publishing"],
  ["comment.", "Comments"],
  ["team.", "Teams"],
  ["invite.", "Invites"],
];

/** The organizer-readable audit trail: no database client needed. */
export function AuditTab({ event }: { event: EventOut }) {
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<AuditVerify | null>(null);
  const [checking, setChecking] = useState(false);
  const anchorQ = useLoad(() => api.auditAnchor(event.id), [event.id, event.results_published_at ?? ""]);
  const q = useLoad(() => api.audit(event.id, filter || undefined), [event.id, filter], { pollMs: 60_000 });
  useLive(event.id, (t) => t.includes("audit") && q.reload());
  const rows = q.data ?? [];
  const risky = (a: string) => a.includes("flagged") || a.includes("rate_limited") || a.includes("void") || a === "round.close_early" || a.startsWith("round.extend");

  return (
    <section className="panel">
      <div className="panel-head">
        <div><h2>Audit trail</h2><p>Every organizer action and integrity event for this event, newest first. Append-only: the app never edits or deletes these rows.</p></div>
        <div className="row-actions">
          <div className="field field--bar">
            <label htmlFor="audit-filter">Show</label>
            <select id="audit-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
              {FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <button className="btn btn--ghost btn--sm" type="button" style={{ alignSelf: "end" }} onClick={() => downloadAuditCsv(event.id).catch((e) => setError(errorText(e)))}>
            <Download size={13} /> Export CSV
          </button>
        </div>
      </div>
      <div className="row-actions" style={{ marginBottom: 12 }}>
        <button
          className="btn btn--cyan btn--sm"
          type="button"
          disabled={checking}
          onClick={() => { setChecking(true); api.auditVerify(event.id).then(setCheck).catch((e) => setError(errorText(e))).finally(() => setChecking(false)); }}
        >
          <ShieldCheck size={13} /> {checking ? "Checking…" : "Verify integrity"}
        </button>
        <span className="muted">Each entry is chained to the one before it, so any edit or deletion is detectable.</span>
      </div>
      {check ? (
        <Notice kind={check.ok ? "ok" : "error"} title={check.ok ? `Intact: ${check.checked} entries verified` : "The log has been tampered with"}>
          {check.ok ? `Chain head #${check.head_seq} · ${check.head_hash.slice(0, 16)}…` : `${check.problem} (first bad entry: #${check.first_bad_seq})`}
        </Notice>
      ) : null}
      {anchorQ.data?.published ? (
        <Notice kind={anchorQ.data.verified ? "ok" : "error"} title="Results anchor (public)">
          Published at entry #{anchorQ.data.anchor_seq} · {anchorQ.data.anchor_hash?.slice(0, 16)}… {anchorQ.data.verified ? "The log up to that point still matches." : "The log no longer matches what was published!"}
        </Notice>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
      {q.error ? <Notice kind="error">{q.error}</Notice> : null}
      {rows.length === 0 && !q.loading ? <div className="emptystate">Nothing recorded yet.</div> : (
        <div className="tablewrap">
          <table className="data">
            <thead><tr><th>Time (UTC)</th><th>Who</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{fmtDateTime(r.created_at)}</td>
                  <td>{r.actor_label}</td>
                  <td><span className={`chip ${risky(r.action) ? "chip--coral" : "chip--ghost"}`}>{r.action}</span></td>
                  <td>{r.target_type ? `${r.target_type} ${r.target_id?.slice(0, 8) ?? ""}` : "—"}</td>
                  <td title={r.detail ?? ""}>{truncate(r.detail, 90) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
