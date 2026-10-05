import { useEffect, useState, type FormEvent } from "react";
import {
  CalendarPlus,
  Database,
  Award as AwardIcon,
  Layers,
  Plug,
  ScrollText,
  Vote,
  Download,
  FileCheck2,
  LayoutDashboard,
  Mail,
  Megaphone,
  Plus,
  SlidersHorizontal,
  Trash2,
  Trophy,
  UserCog,
} from "lucide-react";
import {
  api,
  downloadEventExport,
  downloadScoresCsv,
  type EventCreateInput,
  type RoundInput,
  type EventOut,
  type PairwiseRankRow,
  type ResultRow,
} from "../../api/client";
import { ConsoleShell, type ConsoleNavItem } from "../../components/ConsoleShell";
import { Notice } from "../../components/Notice";
import { CertificatesTab } from "./organizer/CertificatesTab";
import { ImportPanel } from "./organizer/ImportPanel";
import { IntegrationsTab } from "./organizer/IntegrationsTab";
import { SimilarityPanel } from "./organizer/SimilarityPanel";
import { RoundsBuilder, draftToInput, newRoundDraft, type RoundDraft } from "../../components/RoundsBuilder";
import { useLive } from "../../hooks/useLive";
import { AuditTab } from "./organizer/AuditTab";
import { JudgesExtras } from "./organizer/JudgesExtras";
import { RoundsTab } from "./organizer/RoundsTab";
import { VotingTab } from "./organizer/VotingTab";
import { NotificationsTab } from "./organizer/NotificationsTab";
import { AutoAssignPanel } from "./organizer/AutoAssignPanel";
import { AnomalyPanel } from "./organizer/AnomalyPanel";
import { CodeScanPanel } from "./organizer/CodeScanPanel";
import { useLoad } from "../../hooks/useLoad";
import { useNow } from "../../hooks/useNow";
import { useSignOut } from "../../hooks/useSignOut";
import { useTab } from "../../hooks/useTab";
import {
  EVENT_STATUS_LABEL,
  errorText,
  fmtAgo,
  fmtDateTime,
  fmtDay,
  inputToIso,
  isPast,
  money,
  shortId,
} from "../../lib/format";
import { useAuthStore } from "../../store/auth";

const nav: ConsoleNavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "events", label: "Events", icon: CalendarPlus },
  { id: "rounds", label: "Rounds", icon: Layers },
  { id: "criteria", label: "Judging criteria", icon: SlidersHorizontal },
  { id: "judges", label: "Judging panel", icon: UserCog },
  { id: "submissions", label: "Submissions", icon: FileCheck2 },
  { id: "results", label: "Results", icon: Trophy },
  { id: "voting", label: "Community voting", icon: Vote },
  { id: "audit", label: "Audit trail", icon: ScrollText },
  { id: "certificates", label: "Certificates", icon: AwardIcon },
  { id: "notifications", label: "Notifications", icon: Mail },
  { id: "integrations", label: "Integrations", icon: Plug },
  { id: "data", label: "Data & records", icon: Database },
];
const TABS = nav.map((n) => n.id);

interface CriterionDraft {
  id: string;
  name: string;
  description: string;
  weight: number;
}
let draftCounter = 0;
const newDraft = (name = "", weight = 0, description = ""): CriterionDraft => ({
  id: `d${++draftCounter}`,
  name,
  weight,
  description,
});
const defaultRubric = (): CriterionDraft[] => [
  newDraft("Functionality", 34, "Does it work as described, end to end?"),
  newDraft("Quality", 33, "Engineering quality, correctness and polish."),
  newDraft("Innovation", 33, "Originality of the idea and the approach taken."),
];

const statusChip = (status: string) =>
  status === "submissions_open" ? "chip--acid" : status === "upcoming" ? "chip--cyan" : "chip--coral";

export default function OrganizerConsole() {
  const user = useAuthStore((s) => s.user);
  const signOut = useSignOut();
  const [active, setActive] = useTab(TABS, "overview");
  const now = useNow();

  const eventsQ = useLoad(api.managedEvents, []);  // organizers see ONLY their own events
  const events: EventOut[] = eventsQ.data ?? [];
  const [pickedId, setPickedId] = useState("");
  const event: EventOut | null = events.find((e) => e.id === pickedId) ?? events[0] ?? null;
  const eid = event?.id ?? "";

  const statsQ = useLoad(() => api.eventStats(eid), [eid], { pollMs: 60_000, enabled: !!eid });
  const annQ = useLoad(() => api.announcements(eid), [eid], { pollMs: 60_000, enabled: !!eid });
  const needsSubs = active === "submissions" || active === "judges";
  const [subRound, setSubRound] = useState("");
  const submissionsQ = useLoad(() => api.eventSubmissions(eid, subRound || undefined), [eid, subRound], { enabled: !!eid && needsSubs });
  const progressQ = useLoad(() => api.eventProgress(eid), [eid], { enabled: !!eid && active === "judges" });
  const judgesQ = useLoad(api.listJudges, [], { enabled: active === "judges" });
  const criteriaQ = useLoad(() => api.getCriteria(eid), [eid], { enabled: !!eid && active === "criteria" });
  const [resRound, setResRound] = useState("");
  const resultsQ = useLoad(() => api.eventResults(eid, resRound || undefined), [eid, resRound], { enabled: !!eid && active === "results" });
  const pairwiseQ = useLoad(() => api.pairwiseResults(eid, resRound || undefined), [eid, resRound], { enabled: !!eid && active === "results" });

  useLive(eid || null, (t) => {
    if (t.includes("stats")) statsQ.reload();
    if (t.includes("announcements")) annQ.reload();
    if (t.some((x) => ["submissions", "progress"].includes(x))) {
      submissionsQ.reload();
      progressQ.reload();
    }
    if (t.some((x) => ["rounds", "results"].includes(x))) eventsQ.reload();
  });
  const stats = statsQ.data;
  const reviewPct = stats && stats.reviews_assigned > 0 ? Math.round((stats.reviews_done / stats.reviews_assigned) * 100) : 0;

  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const flash = (kind: "ok" | "error", text: string) => setMsg({ kind, text });
  const go = (id: string) => {
    setMsg(null);
    setActive(id);
  };

  /* ----------------------------- announcements ----------------------------- */
  const [annBody, setAnnBody] = useState("");
  const postAnnouncement = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    setBusy("announce");
    try {
      await api.postAnnouncement({ ...(eid ? { event_id: eid } : {}), body: annBody });
      setAnnBody("");
      annQ.reload();
      flash("ok", "Announcement posted to the participant feed.");
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(null);
    }
  };

  /* ------------------------------ create event ------------------------------ */
  const [form, setForm] = useState({
    name: "",
    tracks: "",
    starts: "",
    ends: "",
    closes: "",
    prize: "",
    capacity: "",
    description: "",
  });
  const [roundDrafts, setRoundDrafts] = useState<RoundDraft[]>([]);
  const createEvent = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    const closes = inputToIso(form.closes);
    const rounds = roundDrafts.map(draftToInput);
    const badRound = rounds.find((r): r is string => typeof r === "string");
    if (badRound) return flash("error", badRound);
    if (rounds.length === 0 && !closes) {
      flash("error", "Set a valid submission deadline, or add rounds with their own deadlines.");
      return;
    }
    setBusy("event");
    try {
      const prize = Number(form.prize);
      const payload: EventCreateInput = {
        name: form.name.trim(),
        ...(rounds.length === 0 && closes ? { submissions_close: closes } : {}),
        ...(rounds.length > 0 ? { rounds: rounds as RoundInput[] } : {}),
        tracks: form.tracks
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
          .map((name) => ({ name })),
        prizes: prize > 0 ? [{ name: "Prize pool", amount: prize }] : [],
      };
      if (form.description.trim()) payload.description = form.description.trim();
      const starts = inputToIso(form.starts);
      const ends = inputToIso(form.ends, true);
      if (starts) payload.starts_at = starts;
      if (ends) payload.ends_at = ends;
      if (form.capacity) payload.capacity = Number(form.capacity);

      const created = await api.createEvent(payload);
      setForm({ name: "", tracks: "", starts: "", ends: "", closes: "", prize: "", capacity: "", description: "" });
      setRoundDrafts([]);
      setPickedId(created.id);
      eventsQ.reload();
      flash("ok", `Event "${created.name}" created and selected.`);
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(null);
    }
  };

  /* ------------------------------- rubric -------------------------------- */
  const [rubric, setRubric] = useState<CriterionDraft[]>([]);
  const [rubricSaved, setRubricSaved] = useState(false);
  useEffect(() => {
    if (!criteriaQ.data) return;
    if (criteriaQ.data.length > 0) {
      setRubric(criteriaQ.data.map((c) => newDraft(c.name, Number(c.weight), c.description ?? "")));
      setRubricSaved(true);
    } else {
      setRubric(defaultRubric());
      setRubricSaved(false);
    }
  }, [criteriaQ.data]);

  const total = rubric.reduce((sum, c) => sum + c.weight, 0);
  const names = rubric.map((c) => c.name.trim().toLowerCase());
  const rubricProblem =
    rubric.length === 0
      ? "Add at least one criterion."
      : rubric.some((c) => !c.name.trim())
        ? "Every criterion needs a name."
        : new Set(names).size !== names.length
          ? "Criterion names must be unique."
          : rubric.some((c) => c.weight <= 0)
            ? "Every weight must be above 0%."
            : Math.abs(total - 100) > 0.001
              ? `Weights must total 100% (currently ${total}%).`
              : null;

  const patchRubric = (id: string, patch: Partial<CriterionDraft>) =>
    setRubric((cur) => cur.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const distributeEvenly = () =>
    setRubric((cur) => {
      const n = cur.length || 1;
      const base = Math.floor(100 / n);
      const extra = 100 - base * n;
      return cur.map((c, i) => ({ ...c, weight: base + (i < extra ? 1 : 0) }));
    });
  const saveRubric = async () => {
    setMsg(null);
    setBusy("rubric");
    try {
      await api.setCriteria(
        eid,
        rubric.map((c) => ({
          name: c.name.trim(),
          weight: c.weight,
          ...(c.description.trim() ? { description: c.description.trim() } : {}),
        }))
      );
      setRubricSaved(true);
      criteriaQ.reload();
      flash("ok", "Judging criteria saved. Judges now score against this rubric.");
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(null);
    }
  };

  /* ---------------------------- assign a judge ----------------------------- */
  const [judgeEmail, setJudgeEmail] = useState("");
  const [projectId, setProjectId] = useState("");
  const judgeChoice = judgeEmail || judgesQ.data?.[0]?.email || "";
  const projectChoice = projectId || submissionsQ.data?.[0]?.project_id || "";
  const assign = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    setBusy("assign");
    try {
      await api.assignJudge({ judge_email: judgeChoice, project_id: projectChoice });
      const who = judgesQ.data?.find((j) => j.email === judgeChoice)?.name ?? judgeChoice;
      const what = submissionsQ.data?.find((s) => s.project_id === projectChoice)?.title ?? "the project";
      flash("ok", `${who} is now assigned to "${what}".`);
      progressQ.reload();
      submissionsQ.reload();
      statsQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(null);
    }
  };

  /* ------------------------------- exports -------------------------------- */
  const exportCsv = async () => {
    setMsg(null);
    setBusy("csv");
    try {
      await downloadScoresCsv(eid);
      flash("ok", `Scores for "${event?.name ?? "this event"}" downloaded (this event only).`);
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const publish = async (on: boolean) => {
    setMsg(null);
    setBusy("publish");
    try {
      if (on) await api.publishResults(eid, resRound || undefined);
      else await api.unpublishResults(eid);
      eventsQ.reload();
      flash("ok", on ? "Results published. They're now public." : "Results are hidden again.");
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(null);
    }
  };

  /* -------------------------------- results ------------------------------- */
  const ranked = (() => {
    const rows: ResultRow[] = resultsQ.data ?? [];
    const rawRank = new Map(
      [...rows].sort((a, b) => b.raw_average - a.raw_average).map((r, i) => [r.project_id, i + 1] as const)
    );
    return rows.map((r, i) => ({ ...r, rank: i + 1, shift: (rawRank.get(r.project_id) ?? i + 1) - (i + 1) }));
  })();
  const pairRows: PairwiseRankRow[] = pairwiseQ.data ?? [];

  const noEvent = !eventsQ.loading && !event;
  const titles: Record<string, { title: string; subtitle: string }> = {
    overview: { title: "Overview", subtitle: event ? `${event.name} — everything at a glance.` : "Everything at a glance." },
    events: { title: "Events", subtitle: "Create events and see everything that exists." },
    rounds: { title: "Rounds", subtitle: "What teams may submit, when, and who is let in." },
    voting: { title: "Community voting", subtitle: "Ballot settings, live tally and abuse review." },
    certificates: { title: "Certificates", subtitle: "Signed, verifiable certificates for participants, winners and judges." },
    integrations: { title: "Integrations", subtitle: "API keys and webhooks for scripts and other systems." },
    notifications: { title: "Notifications", subtitle: "Emails that send themselves: receipts, reminders, assignments, results and certificates." },
    audit: { title: "Audit trail", subtitle: "Every organizer action and integrity event, readable here." },
    criteria: { title: "Judging criteria", subtitle: "Weighted criteria applied to every submission at this event." },
    judges: { title: "Judging panel", subtitle: "Assign judges to projects and watch progress." },
    submissions: { title: "Submissions", subtitle: "Every submitted project and its review coverage." },
    results: { title: "Results", subtitle: "Provisional standings, normalized for judge severity." },
    data: { title: "Data & records", subtitle: "Exports and imports." },
  };

  const needsEvent = active !== "events" && active !== "data";

  return (
    <ConsoleShell
      role="organizer"
      roleLabel="ORGANIZER ACCESS"
      userName={user?.name ?? "Organizer"}
      userMeta={user?.email ?? ""}
      nav={nav}
      active={active}
      onNavigate={go}
      onSignOut={signOut}
      title={titles[active]!.title}
      subtitle={titles[active]!.subtitle}
      actions={
        events.length > 0 ? (
          <div className="field field--bar">
            <label htmlFor="event-pick">Event</label>
            <select id="event-pick" value={eid} onChange={(e) => setPickedId(e.target.value)}>
              {events.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.name}
                </option>
              ))}
            </select>
          </div>
        ) : undefined
      }
    >
      {eventsQ.error ? <Notice kind="error">{eventsQ.error}</Notice> : null}
      {msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null}
      {noEvent && needsEvent ? (
        <Notice kind="info" title="No events yet">
          Create your first event on the Events tab. Everything else — criteria, judges, submissions, results —
          hangs off an event.
        </Notice>
      ) : null}

      {/* ================================ OVERVIEW ================================ */}
      {active === "overview" && event ? (
        <>
          <div className="grid-4">
            <div className="stat stat--acid">
              <span>ACTIVE EVENTS</span>
              <strong>{events.filter((e) => e.status !== "judging").length}</strong>
              <small>of {events.length} total</small>
            </div>
            <div className="stat stat--cyan">
              <span>PARTICIPANTS</span>
              <strong>{stats ? stats.participants : "—"}</strong>
              <small>
                {stats ? `${stats.teams} teams` : "Loading…"}
                {event.capacity ? ` · capacity ${event.capacity}` : ""}
              </small>
            </div>
            <div className="stat stat--cream">
              <span>REVIEW COMPLETION</span>
              <strong>{stats ? `${reviewPct}%` : "—"}</strong>
              <small>{stats ? `${stats.reviews_done} of ${stats.reviews_assigned} reviews` : "Loading…"}</small>
            </div>
            <div className="stat stat--pink">
              <span>SUBMISSIONS</span>
              <strong>{stats ? stats.submissions : "—"}</strong>
              <small>Deadline {fmtDay(event.submissions_close)}</small>
            </div>
          </div>

          <div className="grid-side">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Event timeline</h2>
                  <p>Derived from this event's real dates.</p>
                </div>
                <span className={`chip ${statusChip(event.status)}`}>{EVENT_STATUS_LABEL[event.status]}</span>
              </div>
              <div className="timeline">
                {[
                  event.starts_at
                    ? { label: "Event starts", detail: fmtDateTime(event.starts_at), done: isPast(event.starts_at, now) }
                    : null,
                  ...event.rounds.map((r) => ({
                    label: `${r.name}${r.closed_early_at ? " (closed early)" : ""}`,
                    detail: `${r.state === "closed" ? "Closed" : r.state === "not_open" ? "Opens later; closes" : "Open until"} ${fmtDateTime(r.closes_at)}${r.state === "closed" ? "" : ": the server locks edits automatically"}`,
                    done: r.state === "closed",
                  })),
                  {
                    label: "Judging",
                    detail: "Assigned judges score their projects",
                    done: !!stats && stats.reviews_assigned > 0 && stats.reviews_done === stats.reviews_assigned,
                  },
                  {
                    label: "Results",
                    detail: "Normalized standings appear on the Results tab",
                    done: false,
                  },
                ]
                  .filter((x): x is { label: string; detail: string; done: boolean } => x !== null)
                  .map((item) => (
                    <div className="tl-item" key={item.label}>
                      <span className={`tl-dot ${item.done ? "" : "tl-dot--muted"}`} />
                      <div className="tl-body">
                        <strong>{item.label}</strong>
                        <span>{item.detail}</span>
                      </div>
                    </div>
                  ))}
              </div>
              <p className="panel-note" style={{ marginTop: 14 }}>
                Counts refresh automatically every few seconds.
              </p>
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Announcements</h2>
                  <p>Shown in this event's participant feed.</p>
                </div>
                <Megaphone size={18} />
              </div>
              <form className="stack" onSubmit={postAnnouncement} style={{ gap: 12 }}>
                <div className="field">
                  <label htmlFor="ann">Message</label>
                  <textarea
                    id="ann"
                    required
                    maxLength={2000}
                    value={annBody}
                    onChange={(e) => setAnnBody(e.target.value)}
                    placeholder="e.g. Submissions close at 18:00 UTC sharp."
                  />
                </div>
                <button className="btn btn--cyan btn--sm" type="submit" disabled={busy === "announce" || !annBody.trim()}>
                  {busy === "announce" ? "Posting…" : "Post announcement"}
                </button>
              </form>
              {annQ.data && annQ.data.length > 0 ? (
                <div className="rowlist" style={{ marginTop: 14 }}>
                  {annQ.data.slice(0, 4).map((a) => (
                    <div className="row" key={a.id}>
                      <div className="row-main">
                        <strong>{a.body}</strong>
                        <span>
                          {a.author_name} · {fmtAgo(a.created_at)}
                          {a.event_id === null ? " · all events" : ""}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          </div>

          <Notice kind="ok" title="Normalization method">
            Each judge's scores are compared against that judge's own average and spread (a z-score, with a floor on
            the spread), so a harsh judge and a generous judge count equally. The full write-up, including the
            measured effect, is in JUDGING.md.
          </Notice>
        </>
      ) : null}

      {/* ================================= EVENTS ================================= */}
      {active === "events" ? (
        <>
          <form className="panel" onSubmit={createEvent}>
            <div className="panel-head">
              <div>
                <h2>Create an event</h2>
                <p>Set the essentials now; you can add the judging rubric right after.</p>
              </div>
            </div>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="ev-name">Event name</label>
                <input id="ev-name" required maxLength={255} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. AI Frontier Hack" />
              </div>
              <div className="field">
                <label htmlFor="ev-tracks">Tracks (comma-separated)</label>
                <input id="ev-tracks" value={form.tracks} onChange={(e) => setForm({ ...form, tracks: e.target.value })} placeholder="AI, Climate, Open" />
              </div>
              <div className="field">
                <label htmlFor="ev-start">Start date</label>
                <input id="ev-start" type="date" value={form.starts} onChange={(e) => setForm({ ...form, starts: e.target.value })} />
              </div>
              <div className="field">
                <label htmlFor="ev-end">End date</label>
                <input id="ev-end" type="date" value={form.ends} onChange={(e) => setForm({ ...form, ends: e.target.value })} />
              </div>
              {roundDrafts.length === 0 ? (
                <div className="field span-2">
                  <label htmlFor="ev-close">Submissions close</label>
                  <input id="ev-close" type="datetime-local" required value={form.closes} onChange={(e) => setForm({ ...form, closes: e.target.value })} />
                  <span className="field-hint">Enforced by the server. Need stages (ideas first, then slides and code)? Add rounds below instead.</span>
                </div>
              ) : null}
              <div className="field">
                <label htmlFor="ev-prize">Prize pool (USD)</label>
                <input id="ev-prize" type="number" min={0} step={1} value={form.prize} onChange={(e) => setForm({ ...form, prize: e.target.value })} placeholder="5000" />
              </div>
              <div className="field">
                <label htmlFor="ev-cap">Capacity</label>
                <input id="ev-cap" type="number" min={1} step={1} value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} placeholder="500" />
              </div>
              <div className="field span-2">
                <label htmlFor="ev-desc">Description</label>
                <textarea id="ev-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
            </div>
            <div className="stack" style={{ marginTop: 18 }}>
              <strong>Rounds {roundDrafts.length === 0 ? "(optional)" : ""}</strong>
              {roundDrafts.length === 0 ? (
                <div>
                  <button type="button" className="btn btn--cyan btn--sm" onClick={() => setRoundDrafts([newRoundDraft(1)])}>Split into rounds</button>
                  <span className="muted" style={{ marginLeft: 10 }}>Each round states what teams may submit: e.g. Round 1 ideas only, Round 2 slides + repo + video.</span>
                </div>
              ) : (
                <RoundsBuilder drafts={roundDrafts} onChange={setRoundDrafts} idPrefix="new" />
              )}
            </div>
            <div className="row-side" style={{ marginTop: 18 }}>
              <button className="btn btn--acid" type="submit" disabled={busy === "event"}>
                {busy === "event" ? "Creating…" : "Create event"}
              </button>
            </div>
          </form>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>All events</h2>
                <p>{events.length} on the platform.</p>
              </div>
            </div>
            {eventsQ.loading ? <div className="emptystate">Loading…</div> : null}
            {!eventsQ.loading && events.length === 0 ? <div className="emptystate">No events yet.</div> : null}
            {events.length > 0 ? (
              <div className="tablewrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Reference</th>
                      <th>Event</th>
                      <th>Tracks</th>
                      <th>Dates</th>
                      <th>Deadline</th>
                      <th>Capacity</th>
                      <th>Prize pool</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((ev) => {
                      const prize = ev.prizes.reduce((sum, p) => sum + (p.amount ?? 0), 0);
                      return (
                        <tr key={ev.id}>
                          <td>{shortId(ev.id)}</td>
                          <td>
                            <strong>{ev.name}</strong>
                          </td>
                          <td>{ev.tracks.map((t) => t.name).join(", ") || "—"}</td>
                          <td>{ev.starts_at ? `${fmtDay(ev.starts_at)} → ${fmtDay(ev.ends_at)}` : "—"}</td>
                          <td>{fmtDateTime(ev.submissions_close)}</td>
                          <td>{ev.capacity ?? "—"}</td>
                          <td>{prize > 0 ? money(prize) : "—"}</td>
                          <td>
                            <span className={`chip ${statusChip(ev.status)}`}>{EVENT_STATUS_LABEL[ev.status]}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      {active === "rounds" && event ? <RoundsTab event={event} onChanged={() => eventsQ.reload()} flash={flash} /> : null}
      {active === "voting" && event ? <VotingTab event={event} onChanged={() => eventsQ.reload()} flash={flash} /> : null}
      {active === "audit" && event ? <AuditTab event={event} /> : null}
      {active === "certificates" && event ? <CertificatesTab event={event} flash={flash} /> : null}
      {active === "integrations" && event ? <IntegrationsTab event={event} flash={flash} /> : null}
      {active === "notifications" && event ? <NotificationsTab event={event} flash={flash} /> : null}

      {/* ================================ CRITERIA ================================ */}
      {active === "criteria" && event ? (
        <>
          <Notice
            kind={rubricProblem ? "error" : "ok"}
            title={rubricProblem ? "Not ready to save" : "Weights total 100%"}
          >
            {rubricProblem ?? "Ready to save. Judges score each criterion from 1 to 5."}
          </Notice>
          {!rubricSaved && !criteriaQ.loading ? (
            <Notice kind="plain" title="No rubric saved yet">
              Until you save one, judges score against three default criteria weighted equally. Edit and save below
              to replace them.
            </Notice>
          ) : null}

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Weight distribution</h2>
                <p>Scale is fixed at 1–5 for every criterion.</p>
              </div>
              <div className="row-side">
                <button className="btn btn--ghost btn--sm" type="button" onClick={distributeEvenly}>
                  Distribute evenly
                </button>
                <button
                  className="btn btn--cyan btn--sm"
                  type="button"
                  onClick={() => setRubric((cur) => [...cur, newDraft("", 0, "")])}
                >
                  <Plus size={14} /> Add criterion
                </button>
              </div>
            </div>
            <div className="weightbar" aria-hidden="true">
              {rubric.map((c) => (
                <i key={c.id} style={{ width: `${Math.max(0, c.weight)}%` }} />
              ))}
            </div>

            <div className="rowlist" style={{ marginTop: 18 }}>
              {rubric.map((c) => (
                <div className="row" key={c.id} style={{ display: "grid", gap: 12 }}>
                  <div className="form-grid">
                    <div className="field">
                      <label>Criterion name</label>
                      <input value={c.name} maxLength={100} onChange={(e) => patchRubric(c.id, { name: e.target.value })} />
                    </div>
                    <div className="field">
                      <label>Weight — {c.weight}%</label>
                      <input
                        className="slider"
                        type="range"
                        min={0}
                        max={100}
                        value={c.weight}
                        aria-label={`${c.name || "criterion"} weight`}
                        onChange={(e) => patchRubric(c.id, { weight: Number(e.target.value) })}
                      />
                    </div>
                    <div className="field span-2">
                      <label>Guidance for judges</label>
                      <input value={c.description} onChange={(e) => patchRubric(c.id, { description: e.target.value })} />
                    </div>
                  </div>
                  <div className="row-side">
                    <button
                      className="btn btn--ghost btn--sm"
                      type="button"
                      onClick={() => setRubric((cur) => cur.filter((x) => x.id !== c.id))}
                    >
                      <Trash2 size={14} /> Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="row-side" style={{ marginTop: 18 }}>
              <button className="btn btn--acid" type="button" disabled={!!rubricProblem || busy === "rubric"} onClick={saveRubric}>
                {busy === "rubric" ? "Saving…" : "Save criteria"}
              </button>
            </div>
          </section>
        </>
      ) : null}

      {/* ================================= JUDGES ================================= */}
      {active === "judges" && event ? (
        <>
          <AutoAssignPanel event={event} flash={flash} onChanged={() => { progressQ.reload(); submissionsQ.reload(); statsQ.reload(); }} />
          <form className="panel" onSubmit={assign}>
            <div className="panel-head">
              <div>
                <h2>Assign one judge manually</h2>
                <p>A judge only ever sees the projects assigned to them. They get an email straight away.</p>
              </div>
            </div>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="as-judge">Judge</label>
                <select id="as-judge" value={judgeChoice} onChange={(e) => setJudgeEmail(e.target.value)}>
                  {(judgesQ.data ?? []).map((j) => (
                    <option key={j.id} value={j.email}>
                      {j.name} — {j.email}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="as-project">Project</label>
                <select id="as-project" value={projectChoice} onChange={(e) => setProjectId(e.target.value)}>
                  {(submissionsQ.data ?? []).map((s) => (
                    <option key={s.project_id} value={s.project_id}>
                      {s.title} — {s.team_name} ({s.assigned} assigned)
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {judgesQ.data && judgesQ.data.length === 0 ? (
              <p className="panel-note" style={{ marginTop: 12 }}>
                No judge accounts exist yet. Judges create their own account with the Judge role.
              </p>
            ) : null}
            <div className="row-side" style={{ marginTop: 18 }}>
              <button className="btn btn--acid" type="submit" disabled={busy === "assign" || !judgeChoice || !projectChoice}>
                {busy === "assign" ? "Assigning…" : "Assign judge"}
              </button>
              <span className="panel-note">The judge is emailed when assigned, and again when scoring opens.</span>
            </div>
          </form>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Panel progress</h2>
                <p>Who has finished, and who hasn't.</p>
              </div>
            </div>
            {progressQ.loading ? <div className="emptystate">Loading…</div> : null}
            {!progressQ.loading && (progressQ.data ?? []).length === 0 ? (
              <div className="emptystate">No judges are assigned to this event yet.</div>
            ) : null}
            <div className="rowlist">
              {(progressQ.data ?? []).map((p) => {
                const pct = p.assigned ? Math.round((p.completed / p.assigned) * 100) : 0;
                return (
                  <div className="row" key={p.judge_user_id}>
                    <div className="row-main" style={{ flex: "1 1 260px" }}>
                      <strong>{p.judge_name || p.judge_email}</strong>
                      <span>{p.judge_email}</span>
                    </div>
                    <div className="row-side">
                      <span className="chip chip--ghost">
                        {p.completed} / {p.assigned} REVIEWED
                      </span>
                      <span className={`chip ${pct === 100 ? "chip--acid" : "chip--cyan"}`}>{pct}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="panel-note" style={{ marginTop: 14 }}>
              Organizers see how many reviews each judge has finished, but not which scores they gave through this view.
            </p>
          </section>
        </>
      ) : null}

      {active === "submissions" && event ? <SimilarityPanel event={event} /> : null}
      {active === "submissions" && event ? <CodeScanPanel event={event} flash={flash} /> : null}
      {active === "judges" && event ? <JudgesExtras event={event} onChanged={() => { progressQ.reload(); submissionsQ.reload(); statsQ.reload(); }} flash={flash} /> : null}

      {/* =============================== SUBMISSIONS ============================== */}
      {active === "submissions" && event ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>All submissions</h2>
              <p>{submissionsQ.data ? `${submissionsQ.data.length} submitted` : "Loading…"}</p>
            </div>
            <div className="row-actions">
              {event.rounds.length > 1 ? (
                <div className="field field--bar">
                  <label htmlFor="sub-round">Round</label>
                  <select id="sub-round" value={subRound} onChange={(e) => setSubRound(e.target.value)}>
                    <option value="">All rounds</option>
                    {event.rounds.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </select>
                </div>
              ) : null}
              <span className="chip chip--cyan">FINAL DEADLINE {fmtDay(event.submissions_close)}</span>
            </div>
          </div>
          {submissionsQ.error ? <Notice kind="error">{submissionsQ.error}</Notice> : null}
          {submissionsQ.data && submissionsQ.data.length === 0 ? <div className="emptystate">Nothing submitted for this event yet.</div> : null}
          {submissionsQ.data && submissionsQ.data.length > 0 ? (
            <div className="tablewrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Reference</th>
                    <th>Round</th>
                    <th>Team</th>
                    <th>Project</th>
                    <th>Track</th>
                    <th>Reviews</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {submissionsQ.data.map((s) => {
                    const state =
                      s.assigned === 0
                        ? { label: "AWAITING ASSIGNMENT", cls: "chip--coral" }
                        : s.reviewed >= s.assigned
                          ? { label: "FULLY REVIEWED", cls: "chip--acid" }
                          : { label: "IN REVIEW", cls: "chip--cyan" };
                    return (
                      <tr key={s.project_id}>
                        <td>{shortId(s.project_id)}</td>
                        <td>{s.round_number ?? "—"}</td>
                        <td>{s.team_name}</td>
                        <td>
                          <strong>{s.title}</strong>
                        </td>
                        <td>{s.track_name ?? "—"}</td>
                        <td>
                          {s.reviewed} / {s.assigned}
                        </td>
                        <td>
                          <span className={`chip ${state.cls}`}>{state.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ================================= RESULTS ================================ */}
      {active === "results" && event ? (
        <>
          <div className="grid-3">
            <div className="stat stat--acid">
              <span>REVIEWS COMPLETE</span>
              <strong>{stats ? `${reviewPct}%` : "—"}</strong>
              <small>{stats ? `${stats.reviews_done} of ${stats.reviews_assigned}` : "Loading…"}</small>
            </div>
            <div className="stat stat--cyan">
              <span>NORMALIZATION</span>
              <strong style={{ fontSize: 24 }}>Z-SCORE</strong>
              <small>Per-judge, with a spread floor</small>
            </div>
            <div className="stat stat--cream">
              <span>PUBLICATION</span>
              <strong style={{ fontSize: 22 }}>{event.results_published_at ? "PUBLIC" : "HIDDEN"}</strong>
              <small>{event.results_published_at ? `Published ${fmtDateTime(event.results_published_at)}` : "Only you can see results until you publish"}</small>
            </div>
          </div>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Provisional standings</h2>
                <p>Ranked by normalized score. “Shift” compares against the ranking by raw average.</p>
              </div>
              <div className="row-actions">
                {event.rounds.length > 1 ? (
                  <div className="field field--bar">
                    <label htmlFor="res-round">Round</label>
                    <select id="res-round" value={resRound} onChange={(e) => setResRound(e.target.value)}>
                      <option value="">Latest scored round</option>
                      {event.rounds.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                  </div>
                ) : null}
                <button className="btn btn--ghost btn--sm" type="button" onClick={exportCsv} disabled={busy === "csv"}>
                  <Download size={14} /> {busy === "csv" ? "Exporting…" : "Export CSV (this event)"}
                </button>
              </div>
            </div>
            {resultsQ.loading ? <div className="emptystate">Loading…</div> : null}
            {resultsQ.error ? <Notice kind="error">{resultsQ.error}</Notice> : null}
            {resultsQ.data && ranked.length === 0 ? (
              <div className="emptystate">No scored projects yet. Assign judges, then their reviews appear here.</div>
            ) : null}
            {ranked.length > 0 ? (
              <div className="tablewrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Team</th>
                      <th>Project</th>
                      <th>Judges</th>
                      <th>Raw avg (1–5)</th>
                      <th>Normalized (z)</th>
                      <th>Shift</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((r) => (
                      <tr key={r.project_id}>
                        <td>
                          <strong>{String(r.rank).padStart(2, "0")}</strong>
                        </td>
                        <td>{r.team_name}</td>
                        <td>
                          <strong>{r.project_title}</strong>
                        </td>
                        <td>{r.judge_count}</td>
                        <td>{r.raw_average.toFixed(2)}</td>
                        <td>{r.normalized_score.toFixed(2)}</td>
                        <td>
                          <span className={`chip ${r.shift > 0 ? "chip--acid" : r.shift < 0 ? "chip--coral" : "chip--ghost"}`}>
                            {r.shift > 0 ? `▲ ${r.shift}` : r.shift < 0 ? `▼ ${-r.shift}` : "="}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Publish results</h2>
                <p>Makes the judges' ranking, winners (prizes go to ranks in order of size) and community vote totals public. Needs the round's submissions closed and voting not open.</p>
              </div>
              <div className="row-actions">
                {event.results_published_at ? (
                  <button className="btn btn--ghost btn--sm" type="button" disabled={busy === "publish"} onClick={() => window.confirm("Hide the results from the public again?") && void publish(false)}>
                    Unpublish
                  </button>
                ) : (
                  <button className="btn btn--acid btn--sm" type="button" disabled={busy === "publish"} onClick={() => window.confirm("Publish these results to the public? Everyone will be able to see them.") && void publish(true)}>
                    {busy === "publish" ? "Publishing…" : "Publish results"}
                  </button>
                )}
              </div>
            </div>
            {event.results_published_at ? <p className="panel-note">Live at <code>/results/{event.id}</code>.</p> : null}
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Head-to-head ranking</h2>
                <p>Bradley–Terry strengths from judges' pairwise picks — an alternative view of the same event.</p>
              </div>
            </div>
            {pairwiseQ.data && pairRows.length === 0 ? (
              <div className="emptystate">No head-to-head comparisons yet. Judges make them in their Head-to-head tab.</div>
            ) : null}
            {pairRows.length > 0 ? (
              <div className="tablewrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Team</th>
                      <th>Project</th>
                      <th>Comparisons</th>
                      <th>Strength</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pairRows.map((r, i) => (
                      <tr key={r.project_id}>
                        <td>
                          <strong>{String(i + 1).padStart(2, "0")}</strong>
                        </td>
                        <td>{r.team_name}</td>
                        <td>
                          <strong>{r.project_title}</strong>
                        </td>
                        <td>{r.comparisons}</td>
                        <td>{r.strength.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
          <AnomalyPanel event={event} roundId={resRound || undefined} />
        </>
      ) : null}

      {/* ================================== DATA ================================== */}
      {active === "data" ? (
        <div className="grid-2">
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Export records</h2>
                <p>Download data for reporting and archives.</p>
              </div>
            </div>
            <div className="rowlist">
              <div className="row">
                <div className="row-main">
                  <strong>Scores with criteria breakdown</strong>
                  <span>{event ? `Every judge's scores and comments for "${event.name}" only` : "Choose an event first"}, as CSV</span>
                </div>
                <button className="btn btn--cyan btn--sm" type="button" onClick={exportCsv} disabled={busy === "csv" || !event}>
                  <Download size={14} /> {busy === "csv" ? "Exporting…" : "Export"}
                </button>
              </div>
              {([
                ["teams.csv", "Teams and members", "Every team with each member's name and email"],
                ["projects.csv", "Submissions", "Every submission (same columns the importer reads, so it round-trips)"],
                ["bundle.json", "Whole event bundle", "Rounds, tracks, prizes, criteria, teams, projects and awards as JSON"],
              ] as const).map(([file, label, help]) => (
                <div className="row" key={file}>
                  <div className="row-main">
                    <strong>{label}</strong>
                    <span>{event ? `${help} for "${event.name}" only` : "Choose an event first"}</span>
                  </div>
                  <button className="btn btn--cyan btn--sm" type="button" disabled={!event} onClick={() => event && downloadEventExport(event.id, file).then(() => flash("ok", `${label} downloaded.`)).catch((e) => flash("error", errorText(e)))}>
                    <Download size={14} /> Export
                  </button>
                </div>
              ))}
            </div>
          </section>

          {event ? (
            <ImportPanel event={event} flash={flash} onImported={() => { eventsQ.reload(); statsQ.reload(); submissionsQ.reload(); }} />
          ) : (
            <section className="panel"><div className="emptystate">Create or choose an event to import into.</div></section>
          )}
        </div>
      ) : null}
    </ConsoleShell>
  );
}
