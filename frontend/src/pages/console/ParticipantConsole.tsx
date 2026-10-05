import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Award, Box, Copy, Gamepad2, Heart, Megaphone, Rocket, Search, Trophy, Upload, UserPlus, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type ProjectOut, type ProjectPublic, type TeamMine } from "../../api/client";
import { CommentsThread } from "../../components/CommentsThread";
import { FileList } from "../../components/FileList";
import { MyCertificates } from "../../components/MyCertificates";
import { useLive } from "../../hooks/useLive";
import { ConsoleShell, type ConsoleNavItem } from "../../components/ConsoleShell";
import { Notice } from "../../components/Notice";
import { InviteByEmail, MailPreferences } from "../../components/EmailTools";
import { useLoad } from "../../hooks/useLoad";
import { useNow } from "../../hooks/useNow";
import { useSignOut } from "../../hooks/useSignOut";
import { useTab } from "../../hooks/useTab";
import { errorText, fmtAgo, fmtDateTime, isPast, timeLeft } from "../../lib/format";
import { useAuthStore } from "../../store/auth";

const nav: ConsoleNavItem[] = [
  { id: "hub", label: "Player hub", icon: Gamepad2 },
  { id: "squad", label: "My squad", icon: Users },
  { id: "build", label: "My build", icon: Box },
  { id: "gallery", label: "Gallery", icon: Heart },
  { id: "rankings", label: "Results", icon: Trophy },
];
const TABS = nav.map((n) => n.id);

interface BuildDraft {
  title: string;
  track_id: string;
  repo_url: string;
  video_url: string;
  tech_stack: string;
  summary: string;
}
const EMPTY_BUILD: BuildDraft = { title: "", track_id: "", repo_url: "", video_url: "", tech_stack: "", summary: "" };

const fromProject = (p: ProjectOut | null | undefined): BuildDraft => {
  return p
    ? {
        title: p.title,
        track_id: p.track_id ?? "",
        repo_url: p.repo_url ?? "",
        video_url: p.video_url ?? "",
        tech_stack: p.tech_stack ?? "",
        summary: p.summary ?? "",
      }
    : EMPTY_BUILD;
};

export default function ParticipantConsole() {
  const user = useAuthStore((s) => s.user);
  const signOut = useSignOut();
  const [active, setActive] = useTab(TABS, "hub");
  const now = useNow();

  const teamsQ = useLoad(api.myTeams, []);
  const eventsQ = useLoad(api.listEvents, []);
  const teams = teamsQ.data ?? [];
  const [teamIdx, setTeamIdx] = useState(0);
  const team: TeamMine | null = teams[teamIdx] ?? teams[0] ?? null;
  const events = eventsQ.data ?? [];
  const teamEvent = events.find((e) => e.id === team?.event_id) ?? null;
  const openEvents = events.filter((e) => e.status !== "judging");

  const annQ = useLoad(() => api.announcements(team?.event_id), [team?.event_id ?? ""], { pollMs: 15_000 });

  // The deadline that matters: your team's CURRENT ROUND (including any
  // extension the organizers gave your team), else the next open round.
  const currentStatus = team?.rounds.find((r) => r.round_id === team.current_round_id) ?? null;
  const nextOpenRound = openEvents
    .flatMap((e) => e.rounds.filter((r) => r.state === "open"))
    .sort((a, b) => +new Date(a.closes_at) - +new Date(b.closes_at))[0];
  const deadlineIso = currentStatus?.closes_at ?? nextOpenRound?.closes_at ?? null;
  const left = timeLeft(deadlineIso, now);
  const locked = currentStatus
    ? currentStatus.state === "closed" || (currentStatus.state === "open" && isPast(currentStatus.closes_at, now))
    : false;

  // Live: the server nudges us when rounds, teams or announcements change.
  useLive(team?.event_id, (t) => {
    if (t.some((x) => ["rounds", "teams", "submissions"].includes(x))) teamsQ.reload();
    if (t.includes("rounds")) eventsQ.reload();
    if (t.includes("announcements")) annQ.reload();
  });

  /* ---------------------------- squad forms ---------------------------- */
  const [createEventId, setCreateEventId] = useState("");
  const [createName, setCreateName] = useState("");
  // An emailed invite link carries ?code=..., so the join box is pre-filled.
  const [joinCode, setJoinCode] = useState(() => new URLSearchParams(window.location.search).get("code") ?? "");
  const [squadMsg, setSquadMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const eventChoice = createEventId || openEvents[0]?.id || "";

  const createTeam = async (e: FormEvent) => {
    e.preventDefault();
    setSquadMsg(null);
    setBusy("create");
    try {
      const created = await api.createTeam({ event_id: eventChoice, name: createName.trim() });
      setCreateName("");
      setSquadMsg({ kind: "ok", text: `Squad "${created.name}" created. Share code ${created.invite_code} with your crew.` });
      teamsQ.reload();
      setTeamIdx(0);
    } catch (err) {
      setSquadMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  };

  const joinTeam = async (e: FormEvent) => {
    e.preventDefault();
    setSquadMsg(null);
    setBusy("join");
    try {
      const joined = await api.joinTeam(joinCode.trim());
      setJoinCode("");
      setSquadMsg({ kind: "ok", text: `You joined "${joined.name}".` });
      teamsQ.reload();
    } catch (err) {
      setSquadMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  };

  const copyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setSquadMsg({ kind: "error", text: `Couldn't copy automatically — the code is ${code}.` });
    }
  };

  /* ------------------------------- build ------------------------------- */
  const [pickedRound, setPickedRound] = useState("");
  const rs = team?.rounds.find((r) => r.round_id === (pickedRound || team.current_round_id)) ?? team?.rounds[0] ?? null;
  const sub = rs?.submission ?? null;
  const roundLocked = !!rs && (rs.state === "closed" || (rs.state === "open" && isPast(rs.closes_at, now)));
  const canEdit = !!rs && rs.eligible && rs.state === "open" && !roundLocked;
  const [build, setBuild] = useState<BuildDraft>(EMPTY_BUILD);
  const [buildMsg, setBuildMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  useEffect(() => {
    setBuild(fromProject(sub));
    setBuildMsg(null);
    // Reset only when the team, round or submission changes, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [team?.id, rs?.round_id, sub?.id]);

  /** Only send what the round accepts (the server rejects the rest). */
  const roundPayload = () => ({
    title: build.title.trim(),
    track_id: build.track_id || null,
    ...(rs?.allow_idea ? { summary: build.summary.trim(), tech_stack: build.tech_stack.trim() } : {}),
    ...(rs?.allow_repo ? { repo_url: build.repo_url.trim() } : {}),
    ...(rs?.allow_video ? { video_url: build.video_url.trim() } : {}),
  });

  const saveBuild = async (mode: "save" | "replace") => {
    if (!team || !rs) return;
    if (mode === "replace" && !window.confirm("Replace your submission? The current details AND all its files will be deleted.")) return;
    setBuildMsg(null);
    setBusy("build");
    try {
      if (sub && mode === "save") {
        await api.updateProject(sub.id, roundPayload());
        setBuildMsg({ kind: "ok", text: "Changes saved." });
      } else {
        await api.submitProject({ team_id: team.id, round_id: rs.round_id, ...roundPayload() });
        setBuildMsg({ kind: "ok", text: sub ? "Submission replaced. Add your files again below." : "Submitted. You can keep editing until the deadline." });
      }
      teamsQ.reload();
    } catch (err) {
      setBuildMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  };

  const uploadFiles = async (list: FileList | null) => {
    if (!sub || !list || list.length === 0) return;
    setBuildMsg(null);
    setBusy("upload");
    try {
      for (const file of Array.from(list)) await api.uploadFile(sub.id, file);
      setBuildMsg({ kind: "ok", text: `${list.length === 1 ? "File" : "Files"} uploaded.` });
      teamsQ.reload();
    } catch (err) {
      setBuildMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(null);
    }
  };
  const removeFile = async (fileId: string) => {
    if (!sub) return;
    setBuildMsg(null);
    try {
      await api.deleteFile(sub.id, fileId);
      teamsQ.reload();
    } catch (err) {
      setBuildMsg({ kind: "error", text: errorText(err) });
    }
  };

  /* --------------------------- published results --------------------------- */
  const resultsQ = useLoad(() => api.publicResults(team!.event_id), [team?.event_id ?? ""], { enabled: active === "rankings" && !!team });

  /* ------------------------------ gallery ------------------------------ */
  const [q, setQ] = useState("");
  const [qDraft, setQDraft] = useState("");
  const galleryQ = useLoad(() => api.gallery({ q }), [q], { enabled: active === "gallery" });
  const projects: ProjectPublic[] = galleryQ.data ?? [];

  const submissionLabel = !team ? "—" : team.project ? (locked ? "LOCKED" : "SUBMITTED") : locked ? "MISSED" : "NOT YET";
  const countdown = useMemo(
    () => (
      <div className="countdown" aria-label="Time until the submission deadline">
        {[
          [left.days, "DAYS"],
          [left.hours, "HRS"],
          [left.minutes, "MIN"],
        ].map(([value, label]) => (
          <div key={label}>
            <strong>{String(value).padStart(2, "0")}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
    ),
    [left.days, left.hours, left.minutes]
  );

  const titles: Record<string, { title: string; subtitle: string }> = {
    hub: { title: "Player hub", subtitle: "Your run so far. Keep the streak alive." },
    squad: {
      title: "My squad",
      subtitle: team ? `${team.members.length} on the roster. Share your squad code to pull in your crew.` : "Create a squad or join one with a code.",
    },
    build: { title: "My build", subtitle: "Edit freely until the clock hits zero — then it locks." },
    gallery: { title: "Gallery", subtitle: "Browse every shipped build." },
    rankings: { title: "Results", subtitle: "Standings appear once the organizers publish them." },
  };

  // The badge's level follows the landing page's build path:
  // 01 check in · 02 team up · 03 build (draft) · 05 launch (submitted).
  const level = !team ? 1 : !team.project ? 2 : team.project.status === "draft" ? 3 : 5;

  return (
    <ConsoleShell
      role="participant"
      roleLabel={`PLAYER · LVL ${String(level).padStart(2, "0")}`}
      userName={user?.name ?? "Player"}
      userMeta={team ? `${team.name} · ${team.event_name}` : "No squad yet"}
      nav={nav}
      active={active}
      onNavigate={setActive}
      onSignOut={signOut}
      title={titles[active]!.title}
      subtitle={titles[active]!.subtitle}
      actions={
        <>
          {teams.length > 1 ? (
            <div className="field field--bar">
              <label htmlFor="team-pick">Squad</label>
              <select id="team-pick" value={team?.id ?? ""} onChange={(e) => setTeamIdx(teams.findIndex((t) => t.id === e.target.value))}>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} · {t.event_name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {deadlineIso ? (
            left.expired || locked ? (
              <span className="chip chip--coral">SUBMISSIONS CLOSED</span>
            ) : (
              <>
                <span className="chip chip--acid">
                  <Rocket size={12} /> BUILD IN PROGRESS
                </span>
                {countdown}
              </>
            )
          ) : null}
        </>
      }
    >
      {teamsQ.error ? <Notice kind="error">{teamsQ.error}</Notice> : null}

      {active === "hub" ? (
        <>
          <div className="grid-4">
            <div className="stat stat--acid">
              <span>SQUAD</span>
              <strong style={{ fontSize: team && team.name.length > 10 ? 22 : 33 }}>{team ? team.name.toUpperCase() : "NONE"}</strong>
              <small>{team ? team.event_name : "Create or join one"}</small>
            </div>
            <div className="stat stat--cyan">
              <span>SQUAD SIZE</span>
              <strong>{team ? team.members.length : 0}</strong>
              <small>{team ? "on the roster" : "no squad yet"}</small>
            </div>
            <div className="stat stat--pink">
              <span>SUBMISSION</span>
              <strong>{submissionLabel}</strong>
              <small>{!team ? "Needs a squad first" : locked ? "Deadline passed" : team.project ? "Editable until the deadline" : "Editable now"}</small>
            </div>
            <div className="stat stat--cream">
              <span>DEADLINE</span>
              <strong style={{ fontSize: 24 }}>{deadlineIso ? (left.expired || locked ? "CLOSED" : `${left.days}D ${left.hours}H`) : "—"}</strong>
              <small>{deadlineIso ? fmtDateTime(deadlineIso) : "No open event"}</small>
            </div>
          </div>

          <div className="grid-side">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Next objectives</h2>
                  <p>What to do before the deadline.</p>
                </div>
              </div>
              <div className="grid-2">
                <div className="quest-card quest-card--acid">
                  <Box size={22} />
                  <h3>{team?.project ? "POLISH YOUR BUILD" : "LOCK YOUR BUILD"}</h3>
                  <p>
                    {!team
                      ? "Form a squad first, then submit your project."
                      : team.project
                        ? "Submitted. Keep improving it — edits lock at the deadline."
                        : "Add your project details and submit before the clock runs out."}
                  </p>
                  <button className="btn btn--cream btn--sm" type="button" onClick={() => setActive(team ? "build" : "squad")}>
                    {team ? "Open build" : "Open squad"}
                  </button>
                </div>
                <div className="quest-card quest-card--cyan">
                  <Users size={22} />
                  <h3>{team ? "FILL THE SQUAD" : "FIND A SQUAD"}</h3>
                  <p>{team ? `${team.members.length} on the roster. Share code ${team.invite_code}.` : "Create a squad, or join one with a code."}</p>
                  <button className="btn btn--cream btn--sm" type="button" onClick={() => setActive("squad")}>
                    Open squad
                  </button>
                </div>
                <div className="quest-card quest-card--cream">
                  <Heart size={22} />
                  <h3>BACK YOUR FAVOURITES</h3>
                  <p>{teamEvent && teamEvent.voting_mode !== "off" ? "Community voting is on for your event." : "Browse what everyone shipped."}</p>
                  <div className="row-actions">
                    <button className="btn btn--acid btn--sm" type="button" onClick={() => setActive("gallery")}>
                      Open gallery
                    </button>
                    {teamEvent && teamEvent.voting_mode !== "off" ? (
                      <Link className="btn btn--cyan btn--sm" to={`/vote/${teamEvent.id}`}>Vote</Link>
                    ) : null}
                  </div>
                </div>
                <div className="quest-card quest-card--cream">
                  <Award size={22} />
                  <h3>CLAIM YOUR CERT</h3>
                  <p>Certificates appear once the organizers issue them, each with a code anyone can verify.</p>
                  <div className="row-actions">
                    <button className="btn btn--cream btn--sm" type="button" onClick={() => setActive("rankings")}>
                      My certificates
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Launchpad feed</h2>
                  <p>Live from the organizers.</p>
                </div>
                <Megaphone size={18} />
              </div>
              {annQ.data && annQ.data.length > 0 ? (
                <div className="timeline">
                  {annQ.data.slice(0, 6).map((a) => (
                    <div className="tl-item" key={a.id}>
                      <span className="tl-dot" />
                      <div className="tl-body">
                        <strong>{a.body}</strong>
                        <span>
                          {a.author_name} · {fmtAgo(a.created_at)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="emptystate">{annQ.loading ? "Loading…" : "No announcements yet."}</div>
              )}
            </section>
          </div>
        </>
      ) : null}

      {active === "squad" ? (
        <div className="grid-side">
          <section className="panel">
            {team ? (
              <>
                <div className="panel-head">
                  <div>
                    <h2>{team.name.toUpperCase()}</h2>
                    <p>{team.event_name}</p>
                  </div>
                  <span className="chip chip--acid">{team.members.length} MEMBERS</span>
                </div>
                <div className="rowlist">
                  {team.members.map((member) => (
                    <div className="row" key={member.user_id}>
                      <div className="row-main">
                        <strong>{member.name}</strong>
                        <span>{member.is_leader ? "Captain" : "Member"}</span>
                      </div>
                      {member.user_id === user?.id ? <span className="chip chip--ghost">YOU</span> : null}
                    </div>
                  ))}
                </div>
                <div className="field" style={{ marginTop: 18 }}>
                  <span className="field-label" id="squad-code-caption">
                    Your squad code
                  </span>
                  <div className="copy-box" role="group" aria-labelledby="squad-code-caption">
                    <span>{team.invite_code}</span>
                    <button className="btn btn--ghost btn--sm" type="button" onClick={() => copyCode(team.invite_code)}>
                      <Copy size={13} /> {copied ? "Copied" : "Copy"}
                    </button>
                  </div>
                  <span className="field-hint">Anyone with this code can join your squad.</span>
                </div>
                <InviteByEmail teamId={team.id} full={team.members.length >= 4} />
              </>
            ) : (
              <div className="emptystate">{teamsQ.loading ? "Loading…" : "You're not in a squad yet. Create one, or join with a code."}</div>
            )}
          </section>

          <div className="stack">
            {squadMsg ? <Notice kind={squadMsg.kind}>{squadMsg.text}</Notice> : null}

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Create a squad</h2>
                  <p>You become the captain.</p>
                </div>
                <UserPlus size={18} />
              </div>
              {openEvents.length === 0 ? (
                <div className="emptystate">No event is open right now.</div>
              ) : (
                <form className="stack" onSubmit={createTeam} style={{ gap: 12 }}>
                  <div className="field">
                    <label htmlFor="c-event">Event</label>
                    <select id="c-event" value={eventChoice} onChange={(e) => setCreateEventId(e.target.value)}>
                      {openEvents.map((ev) => (
                        <option key={ev.id} value={ev.id}>
                          {ev.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="c-name">Squad name</label>
                    <input id="c-name" required maxLength={255} value={createName} onChange={(e) => setCreateName(e.target.value)} placeholder="e.g. Null Pointers" />
                  </div>
                  <button className="btn btn--acid btn--sm" type="submit" disabled={busy === "create"}>
                    {busy === "create" ? "Creating…" : "Create squad"}
                  </button>
                </form>
              )}
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>Join with a code</h2>
                  <p>Ask a teammate for their squad code.</p>
                </div>
              </div>
              <form className="stack" onSubmit={joinTeam} style={{ gap: 12 }}>
                <div className="field">
                  <label htmlFor="j-code">Squad code</label>
                  <input id="j-code" required value={joinCode} onChange={(e) => setJoinCode(e.target.value)} placeholder="Paste the code" />
                </div>
                <button className="btn btn--cyan btn--sm" type="submit" disabled={busy === "join"}>
                  {busy === "join" ? "Joining…" : "Join squad"}
                </button>
              </form>
            </section>
            <MailPreferences />
          </div>
        </div>
      ) : null}

      {active === "build" ? (
        !team || !rs ? (
          <Notice kind="info" title="Form a squad first">
            Submissions belong to a squad. Create or join one on the My squad tab, then come back here.
          </Notice>
        ) : (
          <>
            {team.rounds.length > 1 ? (
              <div className="round-tabs" role="group" aria-label="Rounds">
                {team.rounds.map((r) => (
                  <button key={r.round_id} type="button" className="round-tab" aria-pressed={r.round_id === rs.round_id} onClick={() => setPickedRound(r.round_id)}>
                    {r.name}{!r.eligible ? " 🔒" : ""}
                  </button>
                ))}
              </div>
            ) : null}

            <Notice
              kind={!rs.eligible ? "info" : canEdit ? "ok" : "error"}
              title={!rs.eligible ? "Not open to your squad yet" : rs.state === "not_open" ? "Not open yet" : canEdit ? "Editing open" : "Submission locked"}
            >
              {!rs.eligible
                ? `${rs.name} is open only to squads the organizers advance. You'll see it unlock here if you're picked.`
                : rs.state === "not_open"
                  ? `${rs.name} hasn't opened for submissions yet.`
                  : canEdit
                    ? `Edit freely until ${fmtDateTime(rs.closes_at)}. After that it's frozen exactly as it stands.`
                    : `${rs.name} is closed. Nothing on this page can be changed; the server rejects late edits.`}
              {rs.instructions ? <span style={{ display: "block", marginTop: 6 }}>Organizers say: {rs.instructions}</span> : null}
            </Notice>

            {buildMsg ? <Notice kind={buildMsg.kind}>{buildMsg.text}</Notice> : null}

            <form
              className={`panel ${canEdit ? "" : "locked"}`}
              onSubmit={(e) => {
                e.preventDefault();
                void saveBuild(sub ? "save" : "replace");
              }}
            >
              <div className="panel-head">
                <div>
                  <h2>{rs.name}</h2>
                  <p>
                    This round accepts:{" "}
                    {[rs.allow_idea && "idea text", rs.allow_repo && "repo link", rs.allow_video && "video link", rs.allow_files && `files (${rs.file_types.join(", ")}, up to ${rs.max_file_mb} MB)`]
                      .filter(Boolean)
                      .join(" · ") || "a title only"}
                    .
                  </p>
                </div>
                <span className={`chip ${sub ? "chip--cyan" : "chip--ghost"}`}>{sub ? sub.status.toUpperCase() : "NOT SUBMITTED"}</span>
              </div>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="b-title">Project name</label>
                  <input id="b-title" required maxLength={255} disabled={!canEdit} value={build.title} onChange={(e) => setBuild({ ...build, title: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="b-track">Track</label>
                  <select id="b-track" disabled={!canEdit} value={build.track_id} onChange={(e) => setBuild({ ...build, track_id: e.target.value })}>
                    <option value="">No track</option>
                    {(teamEvent?.tracks ?? []).map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
                {rs.allow_repo ? (
                  <div className="field">
                    <label htmlFor="b-repo">Repository link</label>
                    <input id="b-repo" type="url" disabled={!canEdit} value={build.repo_url} onChange={(e) => setBuild({ ...build, repo_url: e.target.value })} placeholder="https://github.com/…" />
                  </div>
                ) : null}
                {rs.allow_video ? (
                  <div className="field">
                    <label htmlFor="b-video">Demo video link</label>
                    <input id="b-video" type="url" disabled={!canEdit} value={build.video_url} onChange={(e) => setBuild({ ...build, video_url: e.target.value })} placeholder="Paste a 3-minute walkthrough link" />
                  </div>
                ) : null}
                {rs.allow_idea ? (
                  <>
                    <div className="field span-2">
                      <label htmlFor="b-stack">Tech stack</label>
                      <input id="b-stack" maxLength={500} disabled={!canEdit} value={build.tech_stack} onChange={(e) => setBuild({ ...build, tech_stack: e.target.value })} placeholder="e.g. FastAPI, React, PostgreSQL" />
                    </div>
                    <div className="field span-2">
                      <label htmlFor="b-summary">{rs.allow_repo || rs.allow_files ? "What you built" : "Your idea"}</label>
                      <textarea id="b-summary" disabled={!canEdit} value={build.summary} onChange={(e) => setBuild({ ...build, summary: e.target.value })} />
                    </div>
                  </>
                ) : null}
              </div>
              <div className="row-actions" style={{ marginTop: 18 }}>
                {sub ? (
                  <>
                    <button className="btn btn--acid" type="submit" disabled={busy === "build" || !canEdit}>
                      {busy === "build" ? "Saving…" : "Save changes"}
                    </button>
                    <button className="btn btn--ghost btn--sm" type="button" disabled={busy === "build" || !canEdit} onClick={() => void saveBuild("replace")}>
                      Replace submission
                    </button>
                    <span className="muted">Replacing starts over: the old submission and its files are deleted.</span>
                  </>
                ) : (
                  <button className="btn btn--acid" type="submit" disabled={busy === "build" || !canEdit}>
                    {busy === "build" ? "Submitting…" : "Submit"}
                  </button>
                )}
              </div>
            </form>

            {sub && rs.allow_files ? (
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>Files</h2>
                    <p>Slides, PDFs, screenshots. Only your squad, your assigned judges and the organizers can open them.</p>
                  </div>
                </div>
                <FileList projectId={sub.id} files={sub.files} {...(canEdit ? { onDelete: removeFile } : {})} />
                {canEdit ? (
                  <div className="field" style={{ marginTop: 14 }}>
                    <label htmlFor="b-files"><Upload size={11} /> Add files ({rs.file_types.join(", ")}; max {rs.max_file_mb} MB each)</label>
                    <input id="b-files" type="file" multiple accept={rs.file_types.map((t) => `.${t}`).join(",")} disabled={busy === "upload"} onChange={(e) => { void uploadFiles(e.target.files); e.target.value = ""; }} />
                  </div>
                ) : null}
              </section>
            ) : null}
          </>
        )
      ) : null}

      {active === "gallery" ? (
        <>
          {teamEvent && teamEvent.voting_mode !== "off" ? (
            <Notice kind="info" title="Community voting is on">
              <Link className="link-cyan" to={`/vote/${teamEvent.id}`}>Open the ballot →</Link> (shuffled per voter; results stay hidden until published)
            </Notice>
          ) : null}
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Shipped builds</h2>
                <p>{projects.length} on the board.</p>
              </div>
              <form
                className="row-actions"
                onSubmit={(e) => {
                  e.preventDefault();
                  setQ(qDraft.trim());
                }}
                role="search"
              >
                <div className="field field--bar">
                  <label htmlFor="pg-q">Search</label>
                  <input id="pg-q" value={qDraft} onChange={(e) => setQDraft(e.target.value)} placeholder="Project name…" />
                </div>
                <button className="btn btn--ghost btn--sm" type="submit" style={{ alignSelf: "end" }}>
                  <Search size={14} /> Search
                </button>
              </form>
            </div>
            {galleryQ.loading ? <div className="emptystate">Loading…</div> : null}
            {galleryQ.error ? <Notice kind="error">{galleryQ.error}</Notice> : null}
            {!galleryQ.loading && !galleryQ.error && projects.length === 0 ? <div className="emptystate">No builds match.</div> : null}
            <div className="gallery-grid">
              {projects.map((project) => (
                <article className="gallery-card" key={project.id}>
                  <span className="chip chip--ghost">{project.team_name}</span>
                  <h4>{project.title}</h4>
                  <p>{project.summary || "No description yet."}</p>
                  <div className="gallery-foot">
                    {project.repo_url ? (
                      <a className="link-cyan" href={project.repo_url} target="_blank" rel="noreferrer">
                        REPO →
                      </a>
                    ) : (
                      <span className="muted">{project.track_name ?? "—"}</span>
                    )}
                  </div>
                  <CommentsThread projectId={project.id} />
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}

      {active === "rankings" ? <MyCertificates /> : null}
      {active === "rankings" ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Top of the stack</h2>
              <p>Published by the organizers; hidden until then so nobody plans around a live table.</p>
            </div>
            <Rocket size={18} />
          </div>
          {!team ? <div className="emptystate">Join a squad to see your event's results.</div> : null}
          {team && resultsQ.error ? (
            <div className="soon-block"><strong>Not published yet</strong><p>{resultsQ.error}</p></div>
          ) : null}
          {resultsQ.data ? (
            <div className="stack">
              <Notice kind="ok" title="Results are in">
                {resultsQ.data.winners.length > 0 ? resultsQ.data.winners.map((w) => `${w.prize_name}: ${w.project_title}`).join(" · ") : "Judged and ranked."}
              </Notice>
              <Link className="btn btn--acid" to={`/results/${team!.event_id}`}>See the full results</Link>
            </div>
          ) : null}
        </section>
      ) : null}
    </ConsoleShell>
  );
}
