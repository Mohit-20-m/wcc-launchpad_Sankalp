import { useState } from "react";
import { Lock, Plus, Timer, Trash2, UserPlus } from "lucide-react";
import { api, type EventOut, type RoundOut, type TeamRow } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { RoundsBuilder, draftToInput, newRoundDraft, type RoundDraft } from "../../../components/RoundsBuilder";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtDateTime, inputToIso } from "../../../lib/format";

interface Props {
  event: EventOut;
  onChanged: () => void;
  flash: (kind: "ok" | "error", text: string) => void;
}

const stateChip = (s: string) => (s === "open" ? "chip--acid" : s === "not_open" ? "chip--cyan" : "chip--coral");

function RoundCard({ event, round, teams, onChanged, flash }: { event: EventOut; round: RoundOut; teams: TeamRow[]; onChanged: () => void; flash: Props["flash"] }) {
  const [extendTo, setExtendTo] = useState("");
  const [reason, setReason] = useState("");
  const [teamId, setTeamId] = useState("");
  const [teamTo, setTeamTo] = useState("");
  const [advIds, setAdvIds] = useState<string[]>([]);
  const [topN, setTopN] = useState(3);
  const [busy, setBusy] = useState(false);
  const extQ = useLoad(() => api.listExtensions(event.id, round.id), [event.id, round.id, round.state, round.closes_at]);
  const advQ = useLoad(() => api.listAdvanced(event.id, round.id), [event.id, round.id], { enabled: round.number > 1 });

  const run = async (fn: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    try {
      await fn();
      flash("ok", okText);
      onChanged();
      extQ.reload();
      advQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const [rules, setRules] = useState({ allow_idea: round.allow_idea, allow_repo: round.allow_repo, allow_video: round.allow_video, allow_files: round.allow_files, max_file_mb: round.max_file_mb, open_to_all: round.open_to_all });
  const isLast = event.rounds[event.rounds.length - 1]?.id === round.id;

  return (
    <section className="panel" aria-label={round.name}>
      <div className="panel-head">
        <div>
          <h2>{round.number}. {round.name}</h2>
          <p>{round.instructions || "No instructions set."}</p>
        </div>
        <div className="row-actions">
          <span className={`chip ${stateChip(round.state)}`}>{round.state.replace("_", " ").toUpperCase()}</span>
          {round.closed_early_at ? <span className="chip chip--ghost">CLOSED EARLY</span> : null}
        </div>
      </div>
      <dl className="detail-grid">
        <dt>Closes</dt><dd>{fmtDateTime(round.closes_at)}</dd>
        <dt>Accepts</dt>
        <dd>{[round.allow_idea && "idea text", round.allow_repo && "repo link", round.allow_video && "video link", round.allow_files && `files (${round.file_types.join(", ")}; ${round.max_file_mb} MB)`].filter(Boolean).join(" · ") || "title only"}</dd>
        <dt>Who can enter</dt><dd>{round.open_to_all ? "Every team" : "Only teams you advance"}</dd>
      </dl>

      <div className="stack" style={{ marginTop: 16 }}>
        <div className="row-actions">
          <button className="btn btn--coral btn--sm" type="button" disabled={busy || (round.state === "closed" && (extQ.data ?? []).length === 0)}
            onClick={() => window.confirm(`Stop accepting submissions for ${round.name} now? Judges can start scoring immediately.`) && void run(() => api.closeSubmissions(event.id, round.id), `${round.name} is closed. Judges can score.`)}>
            <Lock size={13} /> Close submissions now
          </button>
          <span className="muted">Ends submissions before the deadline so judges can start scoring.</span>
        </div>

        <div className="form-grid">
          <div className="field">
            <label htmlFor={`ext-${round.id}`}>New deadline for everyone</label>
            <input id={`ext-${round.id}`} type="datetime-local" value={extendTo} onChange={(e) => setExtendTo(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={`extr-${round.id}`}>Reason (shown to participants)</label>
            <input id={`extr-${round.id}`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Wi-Fi outage" />
          </div>
        </div>
        <div className="row-actions">
          <button className="btn btn--acid btn--sm" type="button" disabled={busy || !inputToIso(extendTo)}
            onClick={() => void run(() => api.extendRound(event.id, round.id, { closes_at: inputToIso(extendTo)!, ...(reason.trim() ? { reason: reason.trim() } : {}) }), `${round.name} deadline updated.`)}>
            <Timer size={13} /> {round.state === "closed" ? "Reopen with new deadline" : "Extend deadline"}
          </button>
          <span className="muted">Reopening a round judges already scored keeps their scores; the audit log notes it.</span>
        </div>

        <div className="form-grid">
          <div className="field">
            <label htmlFor={`tm-${round.id}`}>Extend for ONE team</label>
            <select id={`tm-${round.id}`} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
              <option value="">Choose a team…</option>
              {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`tmt-${round.id}`}>Their new deadline</label>
            <input id={`tmt-${round.id}`} type="datetime-local" value={teamTo} onChange={(e) => setTeamTo(e.target.value)} />
          </div>
        </div>
        <div className="row-actions">
          <button className="btn btn--cyan btn--sm" type="button" disabled={busy || !teamId || !inputToIso(teamTo)}
            onClick={() => void run(() => api.extendTeam(event.id, round.id, { team_id: teamId, closes_at: inputToIso(teamTo)!, ...(reason.trim() ? { reason: reason.trim() } : {}) }), "Team extension granted.")}>
            Grant team extension
          </button>
        </div>
        {(extQ.data ?? []).map((x) => (
          <div className="row" key={x.team_id}>
            <div className="row-main"><strong>{x.team_name}</strong><span>extra time until {fmtDateTime(x.closes_at)}{x.reason ? ` — ${x.reason}` : ""}</span></div>
            <button className="btn btn--ghost btn--sm" type="button" disabled={busy} onClick={() => void run(() => api.revokeTeamExtension(event.id, round.id, x.team_id), "Extension revoked.")}>Revoke</button>
          </div>
        ))}

        {round.number > 1 ? (
          <div className="stack" style={{ borderTop: "2px dashed color-mix(in oklab, var(--cream) 25%, transparent)", paddingTop: 14 }}>
            <strong>Advancement into this round</strong>
            {(advQ.data ?? []).length === 0 ? <span className="muted">No teams advanced yet.</span> : null}
            <div className="row-actions">
              {(advQ.data ?? []).map((a) => <span className="chip chip--acid" key={a.team_id}>{a.team_name}</span>)}
            </div>
            <div className="field">
              <label htmlFor={`adv-${round.id}`}>Pick teams to advance (hold Ctrl/Cmd for several)</label>
              <select id={`adv-${round.id}`} multiple size={Math.min(6, Math.max(3, teams.length))} value={advIds}
                onChange={(e) => setAdvIds(Array.from(e.target.selectedOptions, (o) => o.value))}>
                {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <div className="row-actions">
              <button className="btn btn--acid btn--sm" type="button" disabled={busy || advIds.length === 0} onClick={() => void run(() => api.advanceTeams(event.id, round.id, advIds), `${advIds.length} team(s) advanced.`)}>
                <UserPlus size={13} /> Advance selected
              </button>
              <label className="muted" htmlFor={`top-${round.id}`}>or the top</label>
              <input id={`top-${round.id}`} type="number" min={1} max={500} value={topN} style={{ width: 70 }} onChange={(e) => setTopN(Number(e.target.value))} />
              <button className="btn btn--cyan btn--sm" type="button" disabled={busy || topN < 1} onClick={() => void run(() => api.advanceTop(event.id, round.id, topN), `Top ${topN} teams advanced.`)}>
                Advance top {topN} by score
              </button>
            </div>
            <span className="muted">The previous round's submissions must be closed first.</span>
          </div>
        ) : null}

        <details>
          <summary className="muted" style={{ cursor: "pointer" }}>Edit what this round accepts</summary>
          <div className="stack" style={{ marginTop: 10 }}>
            <div className="check-grid">
              {([["allow_idea", "Idea text + tech stack"], ["allow_repo", "Repository link"], ["allow_video", "Video link"], ["allow_files", "File uploads"]] as const).map(([k, label]) => (
                <label key={k}><input type="checkbox" checked={rules[k]} onChange={(e) => setRules({ ...rules, [k]: e.target.checked })} /> {label}</label>
              ))}
              {round.number > 1 ? <label><input type="checkbox" checked={!rules.open_to_all} onChange={(e) => setRules({ ...rules, open_to_all: !e.target.checked })} /> Only teams I advance</label> : null}
            </div>
            <div className="field">
              <label htmlFor={`mb-${round.id}`}>Max file size (MB)</label>
              <input id={`mb-${round.id}`} type="number" min={1} max={50} value={rules.max_file_mb} onChange={(e) => setRules({ ...rules, max_file_mb: Number(e.target.value) })} />
            </div>
            <div className="row-actions">
              <button className="btn btn--acid btn--sm" type="button" disabled={busy} onClick={() => void run(() => api.updateRound(event.id, round.id, rules), "Round rules saved.")}>Save rules</button>
              {isLast && event.rounds.length > 1 ? (
                <button className="btn btn--ghost btn--sm" type="button" disabled={busy} onClick={() => window.confirm(`Remove ${round.name}?`) && void run(() => api.deleteRound(event.id, round.id), "Round removed.")}>
                  <Trash2 size={13} /> Remove this round
                </button>
              ) : null}
            </div>
          </div>
        </details>
      </div>
    </section>
  );
}

export function RoundsTab({ event, onChanged, flash }: Props) {
  const teamsQ = useLoad(() => api.eventTeams(event.id), [event.id]);
  const [adding, setAdding] = useState<RoundDraft[]>([]);
  const [busy, setBusy] = useState(false);

  const addRound = async () => {
    const draft = adding[0];
    if (!draft) return;
    const input = draftToInput(draft);
    if (typeof input === "string") return flash("error", input);
    setBusy(true);
    try {
      await api.addRound(event.id, input);
      setAdding([]);
      flash("ok", `${input.name} added.`);
      onChanged();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Notice kind="plain" title="Rounds run the clock">
        Judges can score a round only after its submissions close: when the deadline passes, or when you close it early
        here. Teams submit once per round; submitting again replaces the earlier one.
      </Notice>
      {event.rounds.map((r) => (
        <RoundCard key={`${r.id}-${r.closes_at}-${r.state}`} event={event} round={r} teams={teamsQ.data ?? []} onChanged={onChanged} flash={flash} />
      ))}
      <section className="panel">
        <div className="panel-head"><div><h2>Add a round</h2><p>Appended after the last round; its deadline must be later.</p></div></div>
        {adding.length === 0 ? (
          <button className="btn btn--cyan btn--sm" type="button" onClick={() => setAdding([newRoundDraft(event.rounds.length + 1)])}><Plus size={14} /> New round</button>
        ) : (
          <div className="stack">
            <RoundsBuilder drafts={adding} onChange={(d) => setAdding(d.slice(0, 1))} idPrefix="add" minRounds={1} allowAdd={false} />
            <div className="row-actions">
              <button className="btn btn--acid" type="button" disabled={busy} onClick={addRound}>{busy ? "Adding…" : "Add round"}</button>
              <button className="btn btn--ghost btn--sm" type="button" onClick={() => setAdding([])}>Cancel</button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
