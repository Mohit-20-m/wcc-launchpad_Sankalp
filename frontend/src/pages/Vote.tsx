import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Minus, Plus, Vote as VoteIcon } from "lucide-react";
import { api, type Ballot } from "../api/client";
import { CommentsThread } from "../components/CommentsThread";
import { Notice } from "../components/Notice";
import { SiteTopbar } from "../components/SiteTopbar";
import { useLive } from "../hooks/useLive";
import { useLoad } from "../hooks/useLoad";
import { errorText, fmtDateTime } from "../lib/format";
import { getVoterToken } from "../lib/voter";
import { useAuthStore } from "../store/auth";

const NAV = [
  { label: "Home", to: "/" },
  { label: "Gallery", to: "/gallery" },
];

/** The public ballot. The server decides who may vote, shuffles the order
 *  per voter, and enforces the limits; this page just shows and submits. */
export default function Vote() {
  const { eventId = "" } = useParams();
  const user = useAuthStore((s) => s.user);
  const [email, setEmail] = useState("");
  const [emailApplied, setEmailApplied] = useState("");
  const voterToken = useMemo(() => getVoterToken(), []);

  const eventsQ = useLoad(api.listEvents, []);
  const cfgQ = useLoad(() => api.votingConfig(eventId), [eventId]);
  const mode = cfgQ.data?.mode;
  const ballotQ = useLoad(
    () => api.ballot(eventId, { voter_token: voterToken, ...(emailApplied ? { email: emailApplied } : {}) }),
    [eventId, emailApplied, user?.id ?? "anon"],
    { enabled: !!cfgQ.data && cfgQ.data.mode !== "off" }
  );
  useLive(eventId, (t) => {
    if (t.includes("voting")) {
      cfgQ.reload();
      ballotQ.reload();
    }
  });

  const ballot: Ballot | null = ballotQ.data;
  const cfg = ballot?.config ?? cfgQ.data;
  const [alloc, setAlloc] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  useEffect(() => {
    if (ballot) setAlloc(Object.fromEntries(ballot.projects.filter((p) => p.my_votes > 0).map((p) => [p.id, p.my_votes])));
  }, [ballot]);

  const quadratic = cfg?.method === "quadratic";
  const cost = Object.values(alloc).reduce((s, v) => s + (quadratic ? v * v : v), 0);
  const budget = quadratic ? cfg?.credits ?? 0 : cfg?.max_votes ?? 0;
  const eventName = eventsQ.data?.find((e) => e.id === eventId)?.name ?? "this event";

  const bump = (id: string, delta: number) =>
    setAlloc((cur) => {
      const next = { ...cur };
      const v = (next[id] ?? 0) + delta;
      if (v <= 0) delete next[id];
      else next[id] = quadratic ? Math.min(v, 20) : 1;
      return next;
    });
  const wouldCost = (id: string) => cost - (quadratic ? (alloc[id] ?? 0) ** 2 : alloc[id] ?? 0) + (quadratic ? ((alloc[id] ?? 0) + 1) ** 2 : 1);

  const submit = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.putBallot(eventId, {
        allocations: Object.entries(alloc).map(([project_id, votes]) => ({ project_id, votes })),
        voter_token: voterToken,
        ...(emailApplied ? { email: emailApplied } : {}),
      });
      ballotQ.reload();
      setMsg({ kind: "ok", text: `Ballot saved. You can change it until voting closes.${res.credits_used ? "" : " (Your ballot is empty.)"}` });
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="public-page">
      <SiteTopbar items={NAV} />
      <main className="public-main">
        <div>
          <span className="chip chip--cyan">
            <VoteIcon size={12} /> COMMUNITY VOTE
          </span>
        </div>
        <h1>
          BACK THE BEST
          <br />
          <em>BUILDS.</em>
        </h1>
        <p className="muted" style={{ maxWidth: 640, margin: 0, lineHeight: 1.7 }}>
          {eventName}.{" "}
          {cfg
            ? quadratic
              ? `Quadratic voting: spend up to ${cfg.credits} credits. Casting n votes on one project costs n × n credits, so spreading your votes goes further than piling them on one project.`
              : `Vote for up to ${cfg.max_votes} projects. Order is shuffled for every voter so nothing wins by being listed first.`
            : ""}
        </p>

        {cfgQ.error ? <Notice kind="error">{cfgQ.error}</Notice> : null}
        {cfg?.mode === "off" ? <Notice kind="info" title="Voting isn't open for this event.">The organizers haven't turned community voting on.</Notice> : null}
        {cfg && cfg.mode !== "off" ? (
          <Notice kind="plain" title={`Voting is ${cfg.state === "open" ? "open" : cfg.state === "not_open" ? "not open yet" : "closed"}`}>
            {cfg.closes_at ? `Closes ${fmtDateTime(cfg.closes_at)}. ` : ""}
            Results stay hidden until the organizers publish them.
            {cfg.results_published ? (
              <>
                {" "}
                <Link className="link-cyan" to={`/results/${eventId}`}>See the results →</Link>
              </>
            ) : null}
          </Notice>
        ) : null}

        {mode === "authenticated" && !user ? (
          <Notice kind="info" title="Sign in to vote">
            This event only counts votes from signed-in accounts.{" "}
            <Link className="link-cyan" to="/login">Sign in →</Link>
          </Notice>
        ) : null}
        {mode === "email_gated" ? (
          <form
            className="searchbar"
            onSubmit={(e) => {
              e.preventDefault();
              setEmailApplied(email.trim());
            }}
          >
            <div className="field">
              <label htmlFor="voter-email">Your email (must be on the organizers' voter list)</label>
              <input id="voter-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@school.edu" required />
            </div>
            <button className="btn btn--acid" type="submit" style={{ alignSelf: "end" }}>Continue</button>
          </form>
        ) : null}

        {ballot && !ballot.can_vote && ballot.reason ? <Notice kind="info">{ballot.reason}</Notice> : null}
        {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
        {ballotQ.error ? <Notice kind="error">{ballotQ.error}</Notice> : null}

        {ballot?.can_vote ? (
          <div className="row-actions vote-bar" role="status">
            <span className="chip chip--acid">
              {quadratic ? `${cost} / ${budget} CREDITS` : `${Object.keys(alloc).length} / ${budget} PROJECTS`}
            </span>
            <button className="btn btn--acid" type="button" onClick={submit} disabled={busy}>
              {busy ? "Saving…" : "Save my ballot"} <ArrowRight size={16} />
            </button>
          </div>
        ) : null}

        <div className="gallery-grid">
          {(ballot?.projects ?? []).map((p) => {
            const v = alloc[p.id] ?? 0;
            return (
              <article className="gallery-card" key={p.id}>
                <span className="chip chip--ghost">{p.team_name}</span>
                <h4>{p.title}</h4>
                <p>{p.summary || "No description yet."}</p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {p.track_name ? <span className="chip chip--cyan">{p.track_name.toUpperCase()}</span> : null}
                  {p.tech_stack ? <span className="chip chip--ghost">{p.tech_stack}</span> : null}
                </div>
                <div className="gallery-foot">
                  <span className="row-actions">
                    {p.repo_url ? <a className="link-cyan" href={p.repo_url} target="_blank" rel="noreferrer">REPO →</a> : null}
                    {p.video_url ? <a className="link-cyan" href={p.video_url} target="_blank" rel="noreferrer">DEMO →</a> : null}
                  </span>
                  {ballot?.can_vote ? (
                    quadratic ? (
                      <span className="row-actions">
                        <button type="button" className="btn btn--ghost btn--sm" aria-label={`Fewer votes for ${p.title}`} onClick={() => bump(p.id, -1)} disabled={v === 0}>
                          <Minus size={13} />
                        </button>
                        <strong aria-label={`Votes for ${p.title}`}>{v}</strong>
                        <button type="button" className="btn btn--cyan btn--sm" aria-label={`More votes for ${p.title}`} onClick={() => bump(p.id, 1)} disabled={wouldCost(p.id) > budget}>
                          <Plus size={13} />
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className={`btn btn--sm ${v ? "btn--acid" : "btn--cyan"}`}
                        aria-pressed={v > 0}
                        onClick={() => bump(p.id, v ? -1 : 1)}
                        disabled={!v && Object.keys(alloc).length >= budget}
                      >
                        {v ? "VOTED ✓" : "VOTE"}
                      </button>
                    )
                  ) : null}
                </div>
                <CommentsThread projectId={p.id} />
              </article>
            );
          })}
        </div>
      </main>
    </div>
  );
}
