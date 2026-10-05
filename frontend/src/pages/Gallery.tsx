import { useMemo, useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type ProjectPublic } from "../api/client";
import { SiteTopbar } from "../components/SiteTopbar";
import { CommentsThread } from "../components/CommentsThread";
import { useLoad } from "../hooks/useLoad";
import { fmtDay } from "../lib/format";

const NAV = [
  { label: "Home", to: "/" },
  { label: "Gallery", to: "/gallery" },
];

/** Public page: no account needed. Anyone can browse what's been built
 *  (the backend serves /projects without auth). */
export default function Gallery() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [trackId, setTrackId] = useState("");
  const [eventId, setEventId] = useState("");

  const eventsQ = useLoad(api.listEvents, []);
  const projectsQ = useLoad(() => api.gallery({ q: query, track_id: trackId, event_id: eventId }), [query, trackId, eventId]);

  const tracks = useMemo(
    () => (eventsQ.data ?? []).filter((e) => !eventId || e.id === eventId).flatMap((e) => e.tracks.map((t) => ({ id: t.id, label: `${e.name} · ${t.name}` }))),
    [eventsQ.data, eventId]
  );
  const projects: ProjectPublic[] = projectsQ.data ?? [];

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    setQuery(draft.trim());
  };

  return (
    <div className="public-page">
      <SiteTopbar items={NAV} />
      <main className="public-main">
        <div>
          <span className="chip chip--cyan">PUBLIC GALLERY</span>
        </div>
        <h1>
          EVERY BUILD.
          <br />
          <em>OUT IN THE OPEN.</em>
        </h1>
        <p className="muted" style={{ maxWidth: 600, margin: 0, lineHeight: 1.7 }}>
          Everything teams have submitted, open to anyone — no account needed.
        </p>

        <form className="searchbar" onSubmit={onSearch} role="search">
          <div className="field">
            <label htmlFor="gallery-q">Search builds</label>
            <input
              id="gallery-q"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search by project name…"
            />
          </div>
          <div className="field">
            <label htmlFor="gallery-event">Event</label>
            <select id="gallery-event" value={eventId} onChange={(e) => { setEventId(e.target.value); setTrackId(""); }}>
              <option value="">All events</option>
              {(eventsQ.data ?? []).map((ev) => (
                <option key={ev.id} value={ev.id}>{ev.name}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="gallery-track">Track</label>
            <select id="gallery-track" value={trackId} onChange={(e) => setTrackId(e.target.value)}>
              <option value="">All tracks</option>
              {tracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <button className="btn btn--acid" type="submit" style={{ alignSelf: "end" }}>
            <Search size={15} /> Search
          </button>
        </form>

        {projectsQ.loading ? <div className="emptystate">Loading builds…</div> : null}
        {projectsQ.error ? <div className="emptystate">Couldn't load the gallery: {projectsQ.error}</div> : null}
        {!projectsQ.loading && !projectsQ.error && projects.length === 0 ? (
          <div className="emptystate">
            {query || trackId ? "No builds match that search." : "Nothing has been submitted yet."}
          </div>
        ) : null}

        <div className="gallery-grid">
          {projects.map((project) => (
            <article className="gallery-card" key={project.id}>
              <span className="chip chip--ghost">{project.team_name || "TEAM"}</span>
              <h4>{project.title}</h4>
              <p>{project.summary || "No description yet."}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {project.track_name ? <span className="chip chip--cyan">{project.track_name.toUpperCase()}</span> : null}
                {project.tech_stack ? <span className="chip chip--ghost">{project.tech_stack}</span> : null}
              </div>
              <div className="gallery-foot">
                <span className="row-actions">
                  {project.repo_url ? (
                    <a className="link-cyan" href={project.repo_url} target="_blank" rel="noreferrer">
                      REPO →
                    </a>
                  ) : null}
                  {project.video_url ? (
                    <a className="link-cyan" href={project.video_url} target="_blank" rel="noreferrer">
                      DEMO →
                    </a>
                  ) : null}
                  {!project.repo_url && !project.video_url ? <span className="muted">SHIPPED {fmtDay(project.submitted_at)}</span> : null}
                </span>
                {(() => {
                  const ev = (eventsQ.data ?? []).find((e) => e.id === project.event_id);
                  if (ev?.results_published_at) return <Link className="link-cyan" to={`/results/${ev.id}`}>RESULTS →</Link>;
                  if (ev && ev.voting_mode !== "off") return <Link className="link-cyan" to={`/vote/${ev.id}`}>VOTE →</Link>;
                  return null;
                })()}
              </div>
              <CommentsThread projectId={project.id} />
            </article>
          ))}
        </div>
      </main>
    </div>
  );
}
