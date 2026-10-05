import { useState } from "react";
import { Code2, RefreshCw } from "lucide-react";
import { api, type EventOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLive } from "../../../hooks/useLive";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtDateTime } from "../../../lib/format";

const SEV: Record<string, string> = { high: "chip--coral", medium: "chip--cyan", info: "chip--ghost" };
const STATUS: Record<string, string> = { done: "chip--acid", pending: "chip--cyan", error: "chip--coral", skipped: "chip--ghost", not_scanned: "chip--ghost" };

/** Repository-level checks: copied code (even with renamed variables),
 *  forks, and commit history outside the event window. Flags only. */
export function CodeScanPanel({ event, flash }: { event: EventOut; flash: (kind: "ok" | "error", text: string) => void }) {
  const q = useLoad(() => api.codeScan(event.id), [event.id], { pollMs: 4000 });
  useLive(event.id, (t) => t.includes("similarity") && q.reload());
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const r = q.data;

  const start = async (force: boolean) => {
    setBusy(true);
    try {
      const res = await api.startCodeScan(event.id, force);
      flash("ok", `Scanning ${res.projects} repositories in the background.`);
      q.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const flaggedProjects = (r?.projects ?? []).filter((p) => p.flags.length);
  const listed = showAll ? r?.projects ?? [] : flaggedProjects;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Code check</h2>
          <p>Reads each submitted GitHub repository and compares the code itself. Renaming variables or reformatting doesn't hide a copy. Also checks for forks and commits made before the event started.</p>
        </div>
        <Code2 size={18} />
      </div>
      {r && !r.github_token ? (
        <Notice kind="plain" title="Tip">Without a GITHUB_TOKEN, GitHub allows about 15 repositories an hour. A token with no permissions at all raises that to thousands.</Notice>
      ) : null}
      <div className="row-actions">
        <button className="btn btn--acid btn--sm" type="button" disabled={busy || r?.running} onClick={() => void start(false)}>{r?.running ? "Scanning…" : "Scan repositories"}</button>
        <button className="btn btn--ghost btn--sm" type="button" disabled={busy || r?.running} onClick={() => void start(true)}><RefreshCw size={12} /> Re-scan everything</button>
      </div>
      {q.error ? <Notice kind="error">{q.error}</Notice> : null}
      {r ? (
        <>
          <p className="panel-note" style={{ marginTop: 12 }}>
            {r.counts.done} scanned · {r.counts.pending} waiting · {r.counts.error} couldn't be read · {r.counts.skipped} not on GitHub
            {r.counts.not_scanned ? ` · ${r.counts.not_scanned} not scanned yet` : ""}
            {r.event_start ? ` · event started ${fmtDateTime(r.event_start)}` : " · set the event's start date to enable the timeline check"}
          </p>

          <h3 style={{ margin: "16px 0 8px" }}>Shared code between teams</h3>
          {r.pairs.length === 0 ? <div className="emptystate">{r.counts.done < 2 ? "Needs at least two scanned repositories." : "No significant code overlap found."}</div> : (
            <div className="rowlist">
              {r.pairs.map((p) => (
                <div className="row" key={`${p.a.project_id}-${p.b.project_id}`} style={{ display: "block" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                    <div className="row-main">
                      <strong>{p.a.title} ↔ {p.b.title}</strong>
                      <span>{p.a.team_name} ({p.a.repo}) · {p.b.team_name} ({p.b.repo})</span>
                    </div>
                    <div className="row-side">
                      <span className="chip chip--coral">{Math.round(p.containment * 100)}% OF THE SMALLER REPO</span>
                      <span className={`chip ${p.kind === "duplicate_entry" ? "chip--cyan" : "chip--ghost"}`}>{p.kind === "duplicate_entry" ? "SAME TEAM" : "DIFFERENT TEAMS"}</span>
                    </div>
                  </div>
                  {p.files.length ? (
                    <ul style={{ margin: "8px 0 0", paddingLeft: 18, lineHeight: 1.6 }}>
                      {p.files.map((f) => <li key={f.a}><code>{f.a}</code> ↔ <code>{f.b}</code> · {Math.round(f.overlap * 100)}% match</li>)}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          <div className="panel-head" style={{ marginTop: 18 }}>
            <div><h3 style={{ margin: 0 }}>Repository timeline</h3><p>{flaggedProjects.length} project(s) with something to check.</p></div>
            <label className="muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show every repository</label>
          </div>
          {listed.length === 0 ? <div className="emptystate">{showAll ? "No submissions yet." : "Nothing flagged."}</div> : (
            <div className="rowlist">
              {listed.map((p) => (
                <div className="row" key={p.project_id} style={{ display: "block" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                    <div className="row-main">
                      <strong>{p.title}</strong>
                      <span>
                        {p.team_name} · {p.repo ?? p.repo_url ?? "no repository"}
                        {p.status === "done" ? ` · ${p.files} files · ${p.commits} commits · first ${fmtDateTime(p.first_commit_at)}` : p.error ? ` · ${p.error}` : ""}
                      </span>
                    </div>
                    <span className={`chip ${STATUS[p.status]}`}>{p.status.replace("_", " ").toUpperCase()}</span>
                  </div>
                  {p.flags.length ? (
                    <div className="stack" style={{ gap: 6, marginTop: 8 }}>
                      {p.flags.map((f, i) => <div key={i}><span className={`chip ${SEV[f.severity]}`}>{f.severity.toUpperCase()}</span> {f.message}</div>)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          <p className="panel-note" style={{ marginTop: 12 }}>
            Method: code is reduced to tokens (names, strings and numbers replaced by placeholders, comments removed) and fingerprinted with winnowing, the algorithm behind Stanford's MOSS. Code that appears in many repositories, like framework starters, is ignored. Everything here is a flag for a human to review.
          </p>
        </>
      ) : null}
    </section>
  );
}
