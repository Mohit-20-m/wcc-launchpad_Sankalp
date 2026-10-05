import { useState } from "react";
import { Activity } from "lucide-react";
import { api, type AnomalyKind, type EventOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLoad } from "../../../hooks/useLoad";

const KIND: Record<AnomalyKind, { label: string; chip: string }> = {
  flat: { label: "SAME SCORE FOR ALL", chip: "chip--coral" },
  reversed: { label: "OPPOSITE TO PEERS", chip: "chip--coral" },
  bias: { label: "CONSISTENT OFFSET", chip: "chip--cyan" },
  outlier: { label: "OUTLIER SCORE", chip: "chip--cyan" },
  influence: { label: "SWINGS THE TOP 3", chip: "chip--cyan" },
  no_separation: { label: "CRITERIA NOT SEPARATED", chip: "chip--ghost" },
};

/** Statistical flags on judges' scoring, compared with their co-judges on
 *  the same projects. Informs the organizer; never changes a score. */
export function AnomalyPanel({ event, roundId }: { event: EventOut; roundId?: string }) {
  const q = useLoad(() => api.anomalies(event.id, roundId), [event.id, roundId ?? ""]);
  const [open, setOpen] = useState<string | null>(null);
  const r = q.data;
  const flagged = (r?.judges ?? []).filter((j) => j.flags.length);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Scoring health check</h2>
          <p>Each judge is compared with the other judges on the same projects. These are prompts for a conversation, not verdicts; nothing is changed automatically.</p>
        </div>
        <Activity size={18} />
      </div>
      {q.error ? <Notice kind="error">{q.error}</Notice> : null}
      {r ? (
        <>
          <div className="grid-3">
            <div className="quest-card"><h3>{r.summary.judges_analysed}</h3><p>judges analysed · {r.summary.reviews} reviews</p></div>
            <div className="quest-card"><h3>{r.summary.judges_flagged}</h3><p>judges with something worth a look</p></div>
            <div className="quest-card"><h3>{r.summary.top3_depends_on_judges}</h3><p>single judges who could change the top 3 on their own{r.summary.top3_depends_on_judges ? " — consider more reviews for leading projects" : ""}</p></div>
          </div>
          {flagged.length === 0 ? <div className="emptystate" style={{ marginTop: 12 }}>No anomalies found{r.summary.reviews ? "" : " (no scores yet)"}.</div> : (
            <div className="rowlist" style={{ marginTop: 14 }}>
              {flagged.map((j) => (
                <div className="row" key={j.judge_user_id} style={{ display: "block" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                    <div className="row-main">
                      <strong>{j.name || j.email}</strong>
                      <span>
                        {j.reviews} reviews · average {j.mean} · spread {j.spread}
                        {j.mean_offset !== null ? ` · ${j.mean_offset > 0 ? "+" : ""}${j.mean_offset} vs co-judges` : ""}
                        {j.agreement !== null ? ` · agreement ${j.agreement}` : ""}
                      </span>
                    </div>
                    <div className="row-side" style={{ flexWrap: "wrap", gap: 6 }}>
                      {[...new Set(j.flags.map((f) => f.kind))].map((k) => <span key={k} className={`chip ${KIND[k].chip}`}>{KIND[k].label}</span>)}
                      <button className="btn btn--ghost btn--sm" type="button" onClick={() => setOpen(open === j.judge_user_id ? null : j.judge_user_id)}>{open === j.judge_user_id ? "Hide" : "Why?"}</button>
                    </div>
                  </div>
                  {open === j.judge_user_id ? (
                    <ul style={{ margin: "10px 0 0", paddingLeft: 18, lineHeight: 1.6 }}>
                      {j.flags.map((f, i) => <li key={i}>{f.message}</li>)}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          <p className="panel-note" style={{ marginTop: 12 }}>
            Checks: identical scores for every project; every criterion given the same number; a consistent offset from co-judges (statistically tested, and already corrected by normalization); single scores 1.5+ points from co-judges; ranking projects opposite to peers; and whether removing one judge would change the top 3.
          </p>
        </>
      ) : <div className="emptystate">{q.loading ? "Analysing…" : ""}</div>}
    </section>
  );
}
