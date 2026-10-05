import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, ClipboardList, EyeOff, Send, Star, Swords } from "lucide-react";
import { api, type PairwisePair, type QueueItem, type ScoreOut } from "../../api/client";
import { ConsoleShell, type ConsoleNavItem } from "../../components/ConsoleShell";
import { Notice } from "../../components/Notice";
import { FileList } from "../../components/FileList";
import { MyCertificates } from "../../components/MyCertificates";
import { useLive } from "../../hooks/useLive";
import { useLoad } from "../../hooks/useLoad";
import { useSignOut } from "../../hooks/useSignOut";
import { useTab } from "../../hooks/useTab";
import { errorText } from "../../lib/format";
import { useAuthStore } from "../../store/auth";

const nav: ConsoleNavItem[] = [
  { id: "queue", label: "My assignments", icon: ClipboardList },
  { id: "score", label: "Scoring", icon: Star },
  { id: "head", label: "Head-to-head", icon: Swords },
  { id: "guidelines", label: "Guidelines", icon: BookOpen },
];
const TABS = nav.map((n) => n.id);

interface CriterionView {
  key: string;
  weight: number;
  guidance: string;
}

/** Used when an organizer hasn't configured a rubric for the event.
 *  Lower-case keys, matching the shape fixtures.json uses. */
const DEFAULT_CRITERIA: CriterionView[] = [
  { key: "functionality", weight: 1, guidance: "Does it work as described, end to end?" },
  { key: "quality", weight: 1, guidance: "Engineering quality, correctness and polish." },
  { key: "innovation", weight: 1, guidance: "Originality of the idea and the approach taken." },
];

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default function JudgeConsole() {
  const user = useAuthStore((s) => s.user);
  const signOut = useSignOut();
  const [active, setActive] = useTab(TABS, "queue");

  const queueQ = useLoad(api.queue, []);
  const scoresQ = useLoad(api.myScores, []);
  const queue: QueueItem[] = queueQ.data ?? [];
  const myScores = scoresQ.data ?? [];
  const scoreByProject = useMemo(() => {
    const map: Record<string, ScoreOut> = {};
    for (const s of myScores) map[s.project_id] = s;
    return map;
  }, [myScores]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected: QueueItem | null =
    queue.find((q) => q.project_id === selectedId) ?? queue.find((q) => !q.scored) ?? queue[0] ?? null;

  const criteriaQ = useLoad(() => api.getCriteria(selected!.event_id), [selected?.event_id ?? ""], {
    enabled: !!selected,
  });
  const configured = criteriaQ.data && criteriaQ.data.length > 0;
  const criteria: CriterionView[] = configured
    ? criteriaQ.data!.map((c) => ({
        key: c.name,
        weight: c.weight,
        guidance: c.description || "Score this criterion from 1 to 5.",
      }))
    : DEFAULT_CRITERIA;
  const criteriaKey = criteria.map((c) => c.key).join("|");

  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [coiOpen, setCoiOpen] = useState(false);
  const [coiReason, setCoiReason] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // Load this project's existing review (if any) into the form. Reset
  // only when the project, the rubric, or the saved scores change.
  useEffect(() => {
    if (!selected) return;
    const existing = scoreByProject[selected.project_id];
    const next: Record<string, number> = {};
    for (const c of criteria) {
      const found = existing
        ? Object.entries(existing.criteria).find(([k]) => k.toLowerCase() === c.key.toLowerCase())
        : undefined;
      next[c.key] = found ? Number(found[1]) : 3;
    }
    setScores(next);
    setComment(existing?.comment ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.project_id, criteriaKey, scoresQ.data]);

  const totalWeight = criteria.reduce((sum, c) => sum + c.weight, 0) || 1;
  const weighted = criteria.reduce((sum, c) => sum + (scores[c.key] ?? 0) * c.weight, 0) / totalWeight;

  const usable = queue.filter((q) => q.scorable).length; // closed rounds, no conflict
  useLive(queue[0]?.event_id, () => {
    queueQ.reload();
    scoresQ.reload();
  });

  const completed = queue.filter((q) => q.scored).length;
  const remaining = queue.length - completed;

  const openScoring = (id: string) => {
    setSelectedId(id);
    setMsg(null);
    setActive("score");
  };

  const submitReview = async () => {
    if (!selected) return;
    setMsg(null);
    setBusy(true);
    try {
      await api.submitScore({
        project_id: selected.project_id,
        criteria: scores,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      });
      queueQ.reload();
      scoresQ.reload();
      setMsg({ kind: "ok", text: `Review saved for "${selected.project_title}".` });
      setActive("queue");
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  const declareConflict = async () => {
    if (!selected) return;
    setMsg(null);
    setBusy(true);
    try {
      await api.declareConflict(selected.project_id, coiReason.trim() || undefined);
      setCoiOpen(false);
      setCoiReason("");
      queueQ.reload();
      setMsg({ kind: "ok", text: "Conflict declared. The organizers have been told and can reassign this project." });
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  /* --------------------------- head-to-head ---------------------------- */
  const [pair, setPair] = useState<PairwisePair | null>(null);
  const [pairErr, setPairErr] = useState<string | null>(null);
  const [pairBusy, setPairBusy] = useState(false);
  const [compared, setCompared] = useState(0);

  const loadPair = useCallback(async () => {
    setPairBusy(true);
    try {
      setPair(await api.nextPair());
      setPairErr(null);
    } catch (err) {
      setPair(null);
      setPairErr(errorText(err));
    } finally {
      setPairBusy(false);
    }
  }, []);

  useEffect(() => {
    if (active === "head" && usable >= 2 && !pair) void loadPair();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, usable]);

  const pick = async (winnerId: string) => {
    if (!pair) return;
    setPairBusy(true);
    try {
      await api.submitComparison({
        project_a_id: pair.project_a_id,
        project_b_id: pair.project_b_id,
        winner_id: winnerId,
      });
      setCompared((n) => n + 1);
    } catch (err) {
      setPairErr(errorText(err));
      setPairBusy(false);
      return;
    }
    await loadPair();
  };
  const summaryOf = (id: string) => queue.find((q) => q.project_id === id)?.project_summary ?? "";

  const titles: Record<string, { title: string; subtitle: string }> = {
    queue: { title: "My assignments", subtitle: "Only the submissions allocated to you are listed here." },
    score: { title: "Scoring", subtitle: "Score against the criteria and weights defined by the organizer." },
    head: { title: "Head-to-head", subtitle: "Skip the numbers — just pick the stronger project." },
    guidelines: { title: "Guidelines", subtitle: "How scoring, confidentiality and normalization work." },
  };

  return (
    <ConsoleShell
      role="judge"
      roleLabel="JUDGE ACCESS"
      userName={user?.name ?? "Judge"}
      userMeta={`Judge · ${queue.length} assigned`}
      nav={nav}
      active={active}
      onNavigate={(id) => {
        setMsg(null);
        setActive(id);
      }}
      onSignOut={signOut}
      title={titles[active]!.title}
      subtitle={titles[active]!.subtitle}
      actions={
        <>
          <span className="chip chip--cyan">
            <EyeOff size={12} /> CONFIDENTIAL SESSION
          </span>
          <span className="chip chip--cream">
            {completed} / {queue.length} COMPLETE
          </span>
        </>
      }
    >
      {queueQ.error ? <Notice kind="error">{queueQ.error}</Notice> : null}

      {active === "queue" ? (
        <>
          {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
          <Notice kind="info" title="Your reviews are private">
            No other judge can see your scores or comments, and you cannot see theirs. This is enforced by the API
            itself — a request for someone else's scores is refused — not by hiding controls on screen.
          </Notice>

          <div className="grid-3">
            <div className="stat stat--acid">
              <span>ASSIGNED TO YOU</span>
              <strong>{queue.length}</strong>
              <small>Allocated by the organizer</small>
            </div>
            <div className="stat stat--cream">
              <span>REVIEWS SUBMITTED</span>
              <strong>{completed}</strong>
              <small>{queue.length ? Math.round((completed / queue.length) * 100) : 0}% of your allocation</small>
            </div>
            <div className="stat stat--cyan">
              <span>REMAINING</span>
              <strong>{remaining}</strong>
              <small>{remaining === 0 && queue.length > 0 ? "All done — thank you" : "Still to review"}</small>
            </div>
          </div>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Submission queue</h2>
                <p>Open a submission to read it in full and record your scores.</p>
              </div>
            </div>
            {queueQ.loading ? <div className="emptystate">Loading…</div> : null}
            {!queueQ.loading && queue.length === 0 ? (
              <div className="emptystate">Nothing assigned to you yet. An organizer assigns projects to judges.</div>
            ) : null}
            <div className="rowlist">
              {queue.map((item) => (
                <div className="row" key={item.project_id}>
                  <div className="row-main" style={{ flex: "1 1 320px" }}>
                    <strong>{item.project_title}</strong>
                    <span>
                      {item.team_name} — {item.track_name ?? "No track"} · {item.event_name}
                      {item.round_name ? ` · ${item.round_name}` : ""}
                    </span>
                  </div>
                  <div className="row-side">
                    <span className={`chip ${item.conflict ? "chip--coral" : item.scored ? "chip--acid" : item.scorable ? "chip--ghost" : "chip--soon"}`}>
                      {item.conflict ? "CONFLICT" : item.scored ? "SUBMITTED" : item.scorable ? "NOT STARTED" : "LOCKED"}
                    </span>
                    <button
                      className={`btn btn--sm ${item.scored || !item.scorable ? "btn--ghost" : "btn--cyan"}`}
                      type="button"
                      onClick={() => openScoring(item.project_id)}
                    >
                      {item.scored ? "View review" : item.scorable ? "Review" : "View details"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <p className="panel-note" style={{ marginTop: 14 }}>
              Team names are shown as reference labels only. A LOCKED project can be read but not scored until its
              round's submissions close (the deadline passes, or the organizer stops submissions early).
            </p>
          </section>
        </>
      ) : null}

      {active === "queue" ? <MyCertificates /> : null}
      {active === "score" ? (
        !selected ? (
          <Notice kind="info" title="Nothing to score yet">
            You have no assigned submissions. An organizer assigns projects to judges.
          </Notice>
        ) : (
          <div className="grid-side">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>{selected.project_title}</h2>
                  <p>
                    {selected.team_name} — {selected.track_name ?? "No track"}
                  </p>
                </div>
                <span className="chip chip--cream">{selected.scored ? "SUBMITTED" : "NOT STARTED"}</span>
              </div>
              <dl className="detail-grid" style={{ marginBottom: 16 }}>
                <dt>Round</dt><dd>{selected.round_name ?? "—"}</dd>
                <dt>Description</dt><dd>{selected.project_summary || "None provided."}</dd>
                <dt>Tech stack</dt><dd>{selected.tech_stack || "None provided."}</dd>
                <dt>Repository</dt>
                <dd>{selected.repo_url ? <a className="link-cyan" href={selected.repo_url} target="_blank" rel="noreferrer">{selected.repo_url}</a> : "None provided."}</dd>
                <dt>Demo video</dt>
                <dd>{selected.video_url ? <a className="link-cyan" href={selected.video_url} target="_blank" rel="noreferrer">{selected.video_url}</a> : "None provided."}</dd>
                <dt>Files</dt>
                <dd><FileList projectId={selected.project_id} files={selected.files} /></dd>
              </dl>

              {selected.conflict ? (
                <Notice kind="error" title="Conflict declared">You declared a conflict of interest on this project, so it can't be scored.</Notice>
              ) : !selected.scorable ? (
                <Notice kind="info" title="Scoring is locked for now">
                  Scoring opens when submissions for {selected.round_name ?? "this round"} close, so you never score work a
                  team can still change. You can read everything they've submitted so far.
                </Notice>
              ) : null}

              {!configured && !criteriaQ.loading ? (
                <Notice kind="plain" title="Default criteria">
                  The organizer hasn't set a rubric for this event, so all three criteria count equally.
                </Notice>
              ) : null}
              {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}

              <div className="rowlist" style={{ marginTop: 14 }}>
                {criteria.map((item) => {
                  const value = scores[item.key] ?? 3;
                  return (
                    <div className="row" key={item.key} style={{ display: "grid", gap: 8 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                        <div className="row-main">
                          <strong>{cap(item.key)}</strong>
                          <span>{item.guidance}</span>
                        </div>
                        <div className="row-side">
                          {configured ? (
                            <span className="chip chip--ghost">
                              WEIGHT {Math.round((item.weight / totalWeight) * 100)}%
                            </span>
                          ) : null}
                          <span className="chip chip--acid">{value} / 5</span>
                        </div>
                      </div>
                      <input
                        className="slider"
                        type="range"
                        min={1}
                        max={5}
                        step={1}
                        value={value}
                        aria-label={`${item.key} score`}
                        disabled={!selected.scorable}
                        onChange={(e) => setScores((cur) => ({ ...cur, [item.key]: Number(e.target.value) }))}
                      />
                    </div>
                  );
                })}
              </div>

              <div className="field" style={{ marginTop: 18 }}>
                <label htmlFor="feedback">Written feedback</label>
                <textarea
                  id="feedback"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="What worked well, and what would you want to see improved?"
                />
                <span className="field-hint">
                  Saved with your review and visible to the event's organizers.
                </span>
              </div>

              <div className="row-side" style={{ marginTop: 18 }}>
                <button className="btn btn--acid" type="button" onClick={submitReview} disabled={busy || !selected.scorable}>
                  <Send size={16} /> {busy ? "Saving…" : selected.scored ? "Update review" : "Submit review"}
                </button>
                <button className="btn btn--ghost btn--sm" type="button" onClick={() => setActive("queue")}>
                  Back to queue
                </button>
                <button
                  className="btn btn--ghost btn--sm"
                  type="button"
                  disabled={selected.scored || selected.conflict}
                  onClick={() => setCoiOpen((v) => !v)}
                  aria-expanded={coiOpen}
                >
                  Declare conflict of interest
                </button>
              </div>
              {coiOpen ? (
                <div className="stack" style={{ marginTop: 14, gap: 10 }}>
                  <div className="field">
                    <label htmlFor="coi-reason">Why? (optional, seen by the organizers)</label>
                    <textarea id="coi-reason" maxLength={500} value={coiReason} onChange={(e) => setCoiReason(e.target.value)} placeholder="e.g. I mentor this team." />
                  </div>
                  <div className="row-actions">
                    <button className="btn btn--coral btn--sm" type="button" disabled={busy} onClick={declareConflict}>Confirm conflict</button>
                    <span className="muted">You won't be able to score or compare this project afterwards.</span>
                  </div>
                </div>
              ) : null}
            </section>

            <div className="stack">
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>Weighted total</h2>
                    <p>Your provisional score before normalization.</p>
                  </div>
                </div>
                <div className="stat stat--acid">
                  <span>WEIGHTED SCORE</span>
                  <strong>{weighted.toFixed(1)}</strong>
                  <small>out of 5</small>
                </div>
                <p className="panel-note" style={{ marginTop: 12 }}>
                  The final published figure may differ once severity normalization is applied across the whole
                  panel.
                </p>
              </section>

              <Notice kind="plain" title="No cross-visibility">
                You will not see another judge's score for this submission at any point.
              </Notice>
            </div>
          </div>
        )
      ) : null}

      {active === "head" ? (
        <>
          <Notice kind="info" title="A different way to judge">
            Instead of inventing a number, look at two of your assigned projects and pick the stronger one. The
            platform turns many of these picks into a ranking (Bradley–Terry, the maths behind chess ratings).
            {compared > 0 ? ` You've made ${compared} this session.` : ""}
          </Notice>

          {usable < 2 && !queueQ.loading ? (
            <Notice kind="plain" title="Need at least two projects ready to judge">
              Head-to-head compares two of your assigned projects whose submissions have closed (and that you haven't
              declared a conflict on).
            </Notice>
          ) : null}
          {pairErr ? <Notice kind="error">{pairErr}</Notice> : null}

          {pair ? (
            <div className="pair-grid">
              <button className="pair-card pair-card--a" type="button" disabled={pairBusy} onClick={() => pick(pair.project_a_id)}>
                <span>OPTION A · THIS ONE IS STRONGER</span>
                <h3>{pair.project_a_title}</h3>
                <p>{summaryOf(pair.project_a_id) || "No description provided."}</p>
              </button>
              <button className="pair-card pair-card--b" type="button" disabled={pairBusy} onClick={() => pick(pair.project_b_id)}>
                <span>OPTION B · THIS ONE IS STRONGER</span>
                <h3>{pair.project_b_title}</h3>
                <p>{summaryOf(pair.project_b_id) || "No description provided."}</p>
              </button>
            </div>
          ) : usable >= 2 && !pairErr ? (
            <div className="emptystate">Loading a pair…</div>
          ) : null}
        </>
      ) : null}

      {active === "guidelines" ? (
        <div className="grid-2">
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Scoring guidance</h2>
                <p>How to use the 1–5 scale consistently.</p>
              </div>
            </div>
            <div className="rowlist">
              {[
                { band: "5", meaning: "Exceptional. Would stand up outside the event." },
                { band: "4", meaning: "Strong. Clearly delivers on the criterion." },
                { band: "3", meaning: "Adequate. Works, with visible gaps." },
                { band: "2", meaning: "Weak. Partially addressed or unreliable." },
                { band: "1", meaning: "Not demonstrated." },
              ].map((item) => (
                <div className="row" key={item.band}>
                  <div className="row-main">
                    <strong>{item.band}</strong>
                    <span>{item.meaning}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Fairness and normalization</h2>
                <p>Why your raw score may shift in the final table.</p>
              </div>
            </div>
            <p className="panel-note">
              Judges naturally differ: some use the full range, others cluster their scores. Rather than asking you
              to adjust your instincts, the platform corrects for it statistically.
            </p>
            <p className="panel-note" style={{ marginTop: 12 }}>
              Each judge's scores are converted to z-scores against that judge's own average and spread (with a floor
              on the spread, so a judge who barely varies can't be over-amplified), then averaged per project. Score
              what you actually see.
            </p>
            <div style={{ marginTop: 16 }}>
              <Notice kind="ok" title="Confidentiality">
                Your scores are stored separately from every other judge's, and the API refuses any request for
                another judge's scores.
              </Notice>
            </div>
            <p className="panel-note" style={{ marginTop: 12 }}>
              Head-to-head mode uses picks instead of numbers, so it avoids scale differences entirely.
            </p>
          </section>
        </div>
      ) : null}
    </ConsoleShell>
  );
}
