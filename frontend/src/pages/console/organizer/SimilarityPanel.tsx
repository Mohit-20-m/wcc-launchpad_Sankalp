import { Copy as CopyIcon } from "lucide-react";
import { api, type EventOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLive } from "../../../hooks/useLive";
import { useLoad } from "../../../hooks/useLoad";

/** Submissions that repeat another (same link, or largely the same
 *  words). For a human to judge: nothing is blocked or penalised. */
export function SimilarityPanel({ event }: { event: EventOut }) {
  const q = useLoad(() => api.similarity(event.id), [event.id]);
  useLive(event.id, (t) => t.includes("similarity") && q.reload());
  const pairs = q.data?.pairs ?? [];
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Possible duplicates</h2>
          <p>Shared repo or video links, or mostly identical descriptions. Boilerplate that many teams use is ignored. This only flags; you decide.</p>
        </div>
        <CopyIcon size={18} />
      </div>
      {q.error ? <Notice kind="error">{q.error}</Notice> : null}
      {pairs.length === 0 && !q.loading ? <div className="emptystate">No duplicates or lookalikes found.</div> : null}
      <div className="rowlist">
        {pairs.map((p) => (
          <div className="row" key={`${p.a.project_id}-${p.b.project_id}`}>
            <div className="row-main">
              <strong>{p.a.title} ↔ {p.b.title}</strong>
              <span>{p.a.team_name}{p.a.team_name === p.b.team_name ? "" : ` / ${p.b.team_name}`} · {p.reasons.join(" · ")}</span>
            </div>
            <span className={`chip ${p.kind === "duplicate_entry" ? "chip--cyan" : "chip--coral"}`}>{p.kind === "duplicate_entry" ? "DUPLICATE ENTRY" : "POSSIBLE COPY"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
