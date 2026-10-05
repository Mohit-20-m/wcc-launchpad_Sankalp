import { useEffect, useState } from "react";
import { Ban, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type EventOut, type VotingMode } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLive } from "../../../hooks/useLive";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtAgo, fmtDateTime, inputToIso } from "../../../lib/format";

interface Props {
  event: EventOut;
  onChanged: () => void;
  flash: (kind: "ok" | "error", text: string) => void;
}

const toLocalInput = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export function VotingTab({ event, onChanged, flash }: Props) {
  const cfgQ = useLoad(() => api.votingConfig(event.id), [event.id]);
  const resultsQ = useLoad(() => api.voteResults(event.id), [event.id], { pollMs: 60_000 });
  const ballotsQ = useLoad(() => api.ballots(event.id), [event.id], { pollMs: 60_000 });
  const listQ = useLoad(() => api.allowlist(event.id), [event.id]);
  useLive(event.id, (t) => {
    if (t.some((x) => ["voting", "ballots"].includes(x))) {
      cfgQ.reload();
      resultsQ.reload();
      ballotsQ.reload();
    }
  });

  const [mode, setMode] = useState<VotingMode>("off");
  const [method, setMethod] = useState<"single" | "quadratic">("single");
  const [opens, setOpens] = useState("");
  const [closes, setCloses] = useState("");
  const [maxVotes, setMaxVotes] = useState(3);
  const [credits, setCredits] = useState(100);
  const [roundId, setRoundId] = useState("");
  const [allow, setAllow] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const c = cfgQ.data;
    if (!c) return;
    setMode(c.mode);
    setMethod(c.method);
    setOpens(toLocalInput(c.opens_at));
    setCloses(toLocalInput(c.closes_at));
    setMaxVotes(c.max_votes);
    setCredits(c.credits);
    setRoundId(c.round_id ?? "");
  }, [cfgQ.data]);
  useEffect(() => {
    if (listQ.data) setAllow(listQ.data.patterns.join("\n"));
  }, [listQ.data]);

  const save = async () => {
    setBusy(true);
    try {
      await api.setVotingConfig(event.id, {
        mode, method, max_votes: maxVotes, credits,
        ...(inputToIso(opens) ? { opens_at: inputToIso(opens)! } : {}),
        ...(inputToIso(closes) ? { closes_at: inputToIso(closes)! } : {}),
        ...(roundId ? { round_id: roundId } : {}),
      });
      flash("ok", "Voting settings saved.");
      cfgQ.reload();
      onChanged();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const saveAllow = async () => {
    setBusy(true);
    try {
      const patterns = allow.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean);
      await api.setAllowlist(event.id, patterns);
      flash("ok", `Voter list saved (${patterns.length} entries).`);
      listQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const setVoid = async (ref: string, void_: boolean) => {
    try {
      await (void_ ? api.voidBallot(event.id, ref) : api.restoreBallot(event.id, ref));
      ballotsQ.reload();
      resultsQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    }
  };

  const cfg = cfgQ.data;
  const url = `${window.location.origin}/vote/${event.id}`;

  return (
    <>
      <Notice kind="plain" title="Results stay hidden">
        Nobody but you can see vote counts, including while voting is open. They become public only when you publish
        results on the Results tab. Ballot order is shuffled per voter by the server.
      </Notice>

      <section className="panel">
        <div className="panel-head">
          <div><h2>Voting settings</h2><p>{cfg ? `Currently ${cfg.state.replace("_", " ")}.` : "Loading…"}</p></div>
          {cfg && cfg.mode !== "off" ? <Link className="link-cyan" to={`/vote/${event.id}`}>Open the public ballot →</Link> : null}
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="v-mode">Who can vote</label>
            <select id="v-mode" value={mode} onChange={(e) => setMode(e.target.value as VotingMode)}>
              <option value="off">Voting off</option>
              <option value="authenticated">Signed-in accounts only</option>
              <option value="email_gated">Emails on my list</option>
              <option value="open_link">Anyone with the link</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="v-method">Voting method</label>
            <select id="v-method" value={method} onChange={(e) => setMethod(e.target.value as "single" | "quadratic")}>
              <option value="single">One vote per project</option>
              <option value="quadratic">Quadratic (n votes cost n²)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="v-open">Opens</label>
            <input id="v-open" type="datetime-local" value={opens} onChange={(e) => setOpens(e.target.value)} />
            <span className="field-hint">Blank = opens when you save.</span>
          </div>
          <div className="field">
            <label htmlFor="v-close">Closes</label>
            <input id="v-close" type="datetime-local" value={closes} onChange={(e) => setCloses(e.target.value)} />
          </div>
          {method === "single" ? (
            <div className="field">
              <label htmlFor="v-max">Max projects per voter</label>
              <input id="v-max" type="number" min={1} max={50} value={maxVotes} onChange={(e) => setMaxVotes(Number(e.target.value))} />
            </div>
          ) : (
            <div className="field">
              <label htmlFor="v-cred">Credits per voter</label>
              <input id="v-cred" type="number" min={1} max={10000} value={credits} onChange={(e) => setCredits(Number(e.target.value))} />
            </div>
          )}
          <div className="field">
            <label htmlFor="v-round">Which round's projects</label>
            <select id="v-round" value={roundId} onChange={(e) => setRoundId(e.target.value)}>
              <option value="">Latest round with submissions</option>
              {event.rounds.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </div>
        </div>
        <div className="row-actions" style={{ marginTop: 16 }}>
          <button className="btn btn--acid" type="button" disabled={busy} onClick={save}>Save voting settings</button>
          <span className="muted">Once ballots exist, the method, limits and round are locked; mode and window can still change.</span>
        </div>
        {mode !== "off" ? <p className="panel-note" style={{ marginTop: 12 }}>Share: <code>{url}</code></p> : null}
      </section>

      {mode === "email_gated" ? (
        <section className="panel">
          <div className="panel-head"><div><h2>Voter list</h2><p>Exact emails and/or whole domains (like @school.edu), one per line. Emails aren't verified by a message (we run offline), so treat this as a gate, not proof of identity.</p></div></div>
          <div className="field">
            <label htmlFor="v-allow">Allowed emails and domains</label>
            <textarea id="v-allow" rows={6} value={allow} onChange={(e) => setAllow(e.target.value)} placeholder={"alex@school.edu\n@partner.org"} />
          </div>
          <div className="row-actions" style={{ marginTop: 12 }}>
            <button className="btn btn--cyan btn--sm" type="button" disabled={busy} onClick={saveAllow}>Save voter list</button>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-head"><div><h2>Live tally</h2><p>Only you can see this until you publish. Voided ballots are excluded.</p></div></div>
        {(resultsQ.data ?? []).length === 0 ? <div className="emptystate">No votes yet.</div> : (
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Rank</th><th>Team</th><th>Project</th><th>Votes</th><th>Voters</th></tr></thead>
              <tbody>
                {(resultsQ.data ?? []).map((r) => (
                  <tr key={r.project_id}><td><strong>{String(r.rank).padStart(2, "0")}</strong></td><td>{r.team_name}</td><td><strong>{r.project_title}</strong></td><td>{r.votes}</td><td>{r.voters}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head"><div><h2>Ballot review</h2><p>One row per voter, identified only by a hash. A ballot is flagged when several different voters share one network address; you can void it.</p></div></div>
        {(ballotsQ.data ?? []).length === 0 ? <div className="emptystate">No ballots yet.</div> : (
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Voter</th><th>Type</th><th>Projects</th><th>Votes</th><th>Credits</th><th>Network</th><th>Updated</th><th>Status</th><th /></tr></thead>
              <tbody>
                {(ballotsQ.data ?? []).map((b) => (
                  <tr key={b.voter_ref}>
                    <td><code>{b.voter_ref.slice(0, 10)}</code></td><td>{b.kind}</td><td>{b.projects}</td><td>{b.votes}</td><td>{b.credits}</td>
                    <td>{b.ip_ref ?? "—"} ({b.shared_ip_voters} voter{b.shared_ip_voters === 1 ? "" : "s"})</td>
                    <td title={fmtDateTime(b.updated_at)}>{fmtAgo(b.updated_at)}</td>
                    <td>
                      {b.voided ? <span className="chip chip--ghost">VOIDED</span> : b.flagged ? <span className="chip chip--coral">FLAGGED</span> : <span className="chip chip--acid">OK</span>}
                    </td>
                    <td>
                      <button className="btn btn--ghost btn--sm" type="button" onClick={() => setVoid(b.voter_ref, !b.voided)}>
                        {b.voided ? <><RotateCcw size={12} /> Restore</> : <><Ban size={12} /> Void</>}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
