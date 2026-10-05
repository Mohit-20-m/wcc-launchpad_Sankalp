import { useParams } from "react-router-dom";
import { Trophy } from "lucide-react";
import { api } from "../api/client";
import { Notice } from "../components/Notice";
import { SiteTopbar } from "../components/SiteTopbar";
import { useLive } from "../hooks/useLive";
import { useLoad } from "../hooks/useLoad";
import { money } from "../lib/format";

const NAV = [
  { label: "Home", to: "/" },
  { label: "Gallery", to: "/gallery" },
];

/** Published results. Public only after the organizer publishes; until
 *  then the API answers 403 and this page says so. */
export default function Results() {
  const { eventId = "" } = useParams();
  const q = useLoad(() => api.publicResults(eventId), [eventId]);
  const anchorQ = useLoad(() => api.auditAnchor(eventId), [eventId]);
  useLive(eventId, (t) => t.includes("results") && q.reload());
  const r = q.data;

  return (
    <div className="public-page">
      <SiteTopbar items={NAV} />
      <main className="public-main">
        <div>
          <span className="chip chip--acid">
            <Trophy size={12} /> RESULTS
          </span>
        </div>
        <h1>
          {r ? r.event_name.toUpperCase() : "RESULTS"}
          <br />
          <em>THE FINAL TABLE.</em>
        </h1>
        {q.loading ? <div className="emptystate">Loading…</div> : null}
        {q.error ? <Notice kind="info" title="Not available yet">{q.error}</Notice> : null}

        {r ? (
          <>
            {r.winners.length > 0 ? (
              <section className="panel">
                <div className="panel-head"><div><h2>Winners</h2><p>Awarded from {r.round_name}.</p></div></div>
                <div className="rowlist">
                  {r.winners.map((w) => (
                    <div className="row" key={w.prize_name}>
                      <div className="row-main">
                        <strong>{w.prize_name}{w.amount ? ` · ${money(w.amount)}` : ""}</strong>
                        <span>{w.project_title} — {w.team_name}</span>
                      </div>
                      <span className="chip chip--acid">#{w.rank}</span>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="panel">
              <div className="panel-head"><div><h2>Judges' ranking</h2><p>{r.round_name}, normalized for judge severity.</p></div></div>
              <div className="tablewrap">
                <table className="data">
                  <thead><tr><th>Rank</th><th>Team</th><th>Project</th><th>Score (z)</th><th>Raw avg</th></tr></thead>
                  <tbody>
                    {r.judges_ranking.map((x) => (
                      <tr key={x.project_id}>
                        <td><strong>{String(x.rank).padStart(2, "0")}</strong></td>
                        <td>{x.team_name}</td>
                        <td><strong>{x.project_title}</strong></td>
                        <td>{x.normalized_score.toFixed(2)}</td>
                        <td>{x.raw_average.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {r.community.length > 0 ? (
              <section className="panel">
                <div className="panel-head"><div><h2>Community favourites</h2><p>Votes from the public ballot.</p></div></div>
                <div className="tablewrap">
                  <table className="data">
                    <thead><tr><th>Rank</th><th>Team</th><th>Project</th><th>Votes</th></tr></thead>
                    <tbody>
                      {r.community.map((x) => (
                        <tr key={x.project_id}>
                          <td><strong>{String(x.rank).padStart(2, "0")}</strong></td>
                          <td>{x.team_name}</td>
                          <td><strong>{x.project_title}</strong></td>
                          <td>{x.votes}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
            {r.audit_anchor ? (
              <Notice kind={anchorQ.data?.verified === false ? "error" : "plain"} title="Tamper-evident record">
                The organizers' audit log is hash-chained. When these results were published it stood at entry #{r.audit_anchor.seq}{" "}
                (<code>{r.audit_anchor.hash.slice(0, 16)}…</code>).{" "}
                {anchorQ.data?.verified === true ? "The log up to that point still matches, so the history behind these results hasn't been rewritten." : anchorQ.data?.verified === false ? "The log no longer matches this anchor!" : ""}
              </Notice>
            ) : null}
          </>
        ) : null}
      </main>
    </div>
  );
}
