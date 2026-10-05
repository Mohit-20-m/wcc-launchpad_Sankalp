import { useEffect, useState } from "react";
import { Shuffle } from "lucide-react";
import { api, type AutoAssignResult, type EventOut, type TrackMode } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLoad } from "../../../hooks/useLoad";
import { errorText } from "../../../lib/format";

interface Props {
  event: EventOut;
  onChanged: () => void;
  flash: (kind: "ok" | "error", text: string) => void;
}

/** Balanced, conflict-free judge assignment with a preview before anything
 *  is written. The organizer picks the pool and tags each judge's tracks. */
export function AutoAssignPanel({ event, onChanged, flash }: Props) {
  const expQ = useLoad(() => api.expertise(event.id), [event.id]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [k, setK] = useState(3);
  const [mode, setMode] = useState<TrackMode>("prefer");
  const [roundId, setRoundId] = useState("");
  const [plan, setPlan] = useState<AutoAssignResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const judges = expQ.data?.judges ?? [];
  const tracks = expQ.data?.tracks ?? [];

  useEffect(() => {
    // Preselect judges already involved in this event (have tracks or work here).
    if (expQ.data) {
      const inEvent = expQ.data.judges.filter((j) => j.in_event).map((j) => j.id);
      setPicked(new Set(inEvent.length ? inEvent : expQ.data.judges.map((j) => j.id)));
    }
  }, [expQ.data]);
  useEffect(() => setPlan(null), [k, mode, roundId, picked]);

  const toggleTrack = async (judgeId: string, trackId: string, current: string[]) => {
    const next = current.includes(trackId) ? current.filter((t) => t !== trackId) : [...current, trackId];
    try {
      await api.setExpertise(event.id, judgeId, next);
      expQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    }
  };

  const runPlan = async (dry: boolean) => {
    setBusy(true);
    try {
      const r = await api.autoAssign(event.id, {
        reviews_per_project: k, track_mode: mode, dry_run: dry, judge_ids: [...picked], ...(roundId ? { round_id: roundId } : {}),
      });
      if (dry) setPlan(r);
      else {
        setPlan(null);
        flash("ok", `Created ${r.assignments.length} assignment(s)${r.emails_queued ? `; emailed ${r.emails_queued} judge(s)` : ""}.`);
        expQ.reload();
        onChanged();
      }
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const visible = showAll ? judges : judges.filter((j) => picked.has(j.id) || j.in_event);
  const s = plan?.summary;

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Auto-assign judges</h2>
          <p>Every project gets the reviews it needs, work is spread evenly, judges who know the track are preferred, and nobody reviews their own team or a declared conflict. Preview first; nothing is saved until you apply.</p>
        </div>
        <Shuffle size={18} />
      </div>

      <div className="form-grid">
        <div className="field">
          <label htmlFor="aa-k">Reviews per project</label>
          <input id="aa-k" type="number" min={1} max={10} value={k} onChange={(e) => setK(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
        </div>
        <div className="field">
          <label htmlFor="aa-mode">Track expertise</label>
          <select id="aa-mode" value={mode} onChange={(e) => setMode(e.target.value as TrackMode)}>
            <option value="prefer">Prefer matching judges</option>
            <option value="strict">Only matching judges</option>
            <option value="ignore">Ignore tracks</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="aa-round">Round</label>
          <select id="aa-round" value={roundId} onChange={(e) => setRoundId(e.target.value)}>
            <option value="">Latest round with submissions</option>
            {event.rounds.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
      </div>

      <div className="panel-head" style={{ marginTop: 18 }}>
        <div><h3 style={{ margin: 0 }}>Judge pool · {picked.size} selected</h3><p>Tick who's judging. Click a track to mark it as that judge's expertise.</p></div>
        <label className="muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show all judge accounts</label>
      </div>
      {expQ.error ? <Notice kind="error">{expQ.error}</Notice> : null}
      {judges.length === 0 && !expQ.loading ? <div className="emptystate">No judge accounts yet. Create an invite code below.</div> : null}
      <div className="rowlist" style={{ maxHeight: 340, overflowY: "auto" }}>
        {visible.map((j) => (
          <div className="row" key={j.id}>
            <label className="row-main" style={{ cursor: "pointer" }}>
              <strong>
                <input type="checkbox" checked={picked.has(j.id)} onChange={(e) => {
                  const next = new Set(picked);
                  if (e.target.checked) next.add(j.id); else next.delete(j.id);
                  setPicked(next);
                }} />{" "}{j.name}
              </strong>
              <span>{j.email} · {j.load} assigned here</span>
            </label>
            <div className="row-side" style={{ flexWrap: "wrap", gap: 6 }}>
              {tracks.length === 0 ? <span className="muted">This event has no tracks</span> : tracks.map((t) => (
                <button key={t.id} type="button" className={`chip ${j.track_ids.includes(t.id) ? "chip--acid" : "chip--ghost"}`} style={{ cursor: "pointer", border: "none" }}
                  aria-pressed={j.track_ids.includes(t.id)} onClick={() => void toggleTrack(j.id, t.id, j.track_ids)}>
                  {t.name}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="row-actions" style={{ marginTop: 16 }}>
        <button className="btn btn--cyan" type="button" disabled={busy || picked.size === 0} onClick={() => void runPlan(true)}>{busy && !plan ? "Planning…" : "Preview assignment"}</button>
        {plan && plan.assignments.length > 0 ? (
          <button className="btn btn--acid" type="button" disabled={busy} onClick={() => void runPlan(false)}>Apply {plan.assignments.length} assignment(s) and email judges</button>
        ) : null}
      </div>

      {plan && s ? (
        <div style={{ marginTop: 18 }}>
          {s.reviews_needed === 0 ? (
            <Notice kind="ok" title="Nothing to do">Every project in {plan.round?.name ?? "this round"} already has {s.reviews_per_project} review(s).</Notice>
          ) : (
            <Notice kind={s.projects_short ? "error" : "ok"} title={`${s.reviews_planned} of ${s.reviews_needed} reviews planned`}>
              {s.projects} projects, {s.judges} judges, at most {s.capacity_per_judge} per judge (load after: {s.load_min}–{s.load_max}).
              {s.track_match_rate !== null ? ` ${Math.round(s.track_match_rate * 100)}% go to a judge who knows the track.` : ""}
              {s.projects_short ? ` ${s.projects_short} project(s) can't be fully covered with this pool.` : ""}
            </Notice>
          )}
          {plan.short.length ? (
            <div className="rowlist" style={{ marginTop: 10 }}>
              {plan.short.map((p) => (
                <div className="row" key={p.project_id}><div className="row-main"><strong>{p.title}</strong><span>needs {p.missing} more · {p.reason}</span></div></div>
              ))}
            </div>
          ) : null}
          {plan.assignments.length ? (
            <div className="tablewrap" style={{ marginTop: 12, maxHeight: 320, overflowY: "auto" }}>
              <table className="data">
                <thead><tr><th>Judge</th><th>Project</th><th>Track</th><th>Match</th></tr></thead>
                <tbody>
                  {plan.assignments.map((a) => (
                    <tr key={`${a.judge_user_id}-${a.project_id}`}>
                      <td>{a.judge_name}</td>
                      <td>{a.project_title}</td>
                      <td>{a.track ?? "—"}</td>
                      <td>{a.track_match === null ? "—" : a.track_match ? <span className="chip chip--acid">EXPERT</span> : <span className="chip chip--ghost">GENERAL</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="panel-note" style={{ marginTop: 10 }}>
            Method: repeated optimal matching (Hungarian algorithm) with a cost for load and track mismatch. Deterministic: applying produces exactly this preview.
          </p>
        </div>
      ) : null}
    </section>
  );
}
