import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Award,
  Box,
  Braces,
  CalendarDays,
  ChevronRight,
  CircleDot,
  Code2,
  Gamepad2,
  Gauge,
  Rocket,
  ShieldCheck,
  Sparkles,
  Swords,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import rocket from "../assets/wcc-rocket.png";
import { api, type EventOut, type PublicResults } from "../api/client";
import { SiteTopbar } from "../components/SiteTopbar";
import { useArcadeSound } from "../hooks/useArcadeSound";
import { useLoad } from "../hooks/useLoad";
import { fmtDay, initials } from "../lib/format";

/* ------------------------------------------------------------------ *
 * Content from the WCC Launchpad design. Tracks, dates and prize are
 * the event's published facts; everything interactive goes to a real
 * page, and the scoreboard switches to real results once published.
 * ------------------------------------------------------------------ */

const eventCards = [
  { title: "AGENTIC AI", track: "WCC LAUNCHPAD 30", date: "4–5 OCT", players: "30 HOURS", prize: "OPEN", tone: "cyan", icon: Braces },
  { title: "OPEN INNOVATION", track: "WCC LAUNCHPAD 30", date: "4–5 OCT", players: "30 HOURS", prize: "OPEN", tone: "lime", icon: Zap },
  { title: "EVERYDAY AUTOMATION", track: "WCC LAUNCHPAD 30", date: "4–5 OCT", players: "30 HOURS", prize: "OPEN", tone: "coral", icon: ShieldCheck },
];

/** The build path. Each step opens the place in the app where it happens. */
const levels = [
  { n: "01", label: "CHECK IN", detail: "Register free and choose your track", icon: Gamepad2, to: "/register" },
  { n: "02", label: "TEAM UP", detail: "Bring a crew of up to four builders", icon: Users, to: "/participant?tab=squad" },
  { n: "03", label: "BUILD", detail: "Turn your idea into a working flow", icon: Code2, to: "/participant?tab=build" },
  { n: "04", label: "DEMO", detail: "Show the one journey that matters", icon: Box, to: "/participant?tab=build" },
  { n: "05", label: "LAUNCH", detail: "Submit and see where you land", icon: Gauge, to: "/participant?tab=build" },
  { n: "06", label: "SHOW IT WORKS", detail: "Present the clearest proof", icon: Trophy, to: "/gallery" },
];

/** Shown until an event publishes results (the design's own preview rows). */
const sampleTeams = [
  { rank: "01", name: "NULL POINTERS", build: "Orbit OS", score: "9,820", unit: "XP", pct: 98, badge: "NP" },
  { rank: "02", name: "BYTE BRAWLERS", build: "Rewild AI", score: "9,540", unit: "XP", pct: 92, badge: "BB" },
  { rank: "03", name: "STACK RAIDERS", build: "Pulse Grid", score: "9,210", unit: "XP", pct: 86, badge: "SR" },
  { rank: "04", name: "CTRL FREAKS", build: "Local Loop", score: "8,870", unit: "XP", pct: 78, badge: "CF" },
];

function ArcadeButton({ children, variant = "acid", onClick }: { children: ReactNode; variant?: "acid" | "light"; onClick?: () => void }) {
  return (
    <button className={`arcade-button arcade-button--${variant}`} onClick={onClick} type="button">
      {children}
    </button>
  );
}

function isOpen(e: EventOut, now: number): boolean {
  return new Date(e.submissions_close).getTime() > now;
}

/** Real standings: the most recently published event's normalized ranking. */
function useLatestResults(events: EventOut[] | null) {
  const latest = useMemo(
    () =>
      (events ?? [])
        .filter((e) => e.results_published_at)
        .sort((a, b) => (b.results_published_at ?? "").localeCompare(a.results_published_at ?? ""))[0] ?? null,
    [events]
  );
  const [results, setResults] = useState<PublicResults | null>(null);
  useEffect(() => {
    let alive = true;
    setResults(null);
    if (latest) {
      api.publicResults(latest.id).then((r) => alive && setResults(r)).catch(() => alive && setResults(null));
    }
    return () => {
      alive = false;
    };
  }, [latest]);
  return results;
}

export default function Landing() {
  const navigate = useNavigate();
  const [activeLevel, setActiveLevel] = useState(2);
  const sound = useArcadeSound();
  const { play } = sound;

  const eventsQ = useLoad(api.listEvents, []);
  const results = useLatestResults(eventsQ.data);
  const anyOpen = (eventsQ.data ?? []).some((e) => isOpen(e, Date.now()));

  useEffect(() => {
    document.documentElement.style.scrollBehavior = "smooth";
    return () => {
      document.documentElement.style.scrollBehavior = "";
    };
  }, []);

  const join = (freq = 720) => {
    play(freq);
    navigate("/register");
  };

  const navItems = [
    { label: "The Event", href: "#arena" },
    { label: "Tracks", href: "#events" },
    { label: "How It Works", href: "#missions" },
    { label: "Scoring", href: "#judging" },
  ];

  // Scoreboard rows: real published results when available, else the preview.
  // Order is the normalized ranking (fair across judges); the number shown is
  // the plain average judge score out of 5, which means something to visitors.
  const ranking = results?.judges_ranking.slice(0, 4) ?? [];
  const rows = ranking.length
    ? ranking.map((r) => ({
        rank: String(r.rank).padStart(2, "0"),
        name: r.team_name.toUpperCase(),
        build: r.project_title,
        score: r.raw_average.toFixed(2),
        unit: "/ 5",
        pct: Math.max(4, Math.round((r.raw_average / 5) * 100)),
        badge: initials(r.team_name),
      }))
    : sampleTeams;

  return (
    <main className="arena-shell">
      <SiteTopbar items={navItems} sound={sound} />

      <section className="hero" id="arena">
        <div className="pixel-grid" aria-hidden="true" />
        <div className="hero-copy">
          <div className="season-tag">
            <CircleDot size={13} /> NATIONAL · ONLINE · FREE TO ENTER
          </div>
          <p className="eyebrow">04 — 05 OCTOBER 2026 / 30 HOURS</p>
          <h1>
            <span>WCC</span>
            <span>LAUNCHPAD</span>
            <span>30.</span>
          </h1>
          <p className="hero-deck">
            Thirty hours to turn one problem worth solving into a working product. No startup, rehearsed pitch, or years
            of experience required. Just a team and the willingness to build.
          </p>
          <div className="hero-actions">
            <Link to="/register" className="arcade-button arcade-button--acid" onClick={() => play(760)}>
              <Rocket size={20} /> JOIN THE BUILD <ArrowRight size={20} />
            </Link>
            <ArcadeButton variant="light" onClick={() => document.querySelector("#events")?.scrollIntoView()}>
              EXPLORE TRACKS
            </ArcadeButton>
          </div>
          <div className="hero-proof">
            <div>
              <strong>30</strong>
              <span>HOURS TO BUILD</span>
            </div>
            <div>
              <strong>₹50K</strong>
              <span>CASH PRIZE</span>
            </div>
            <div>
              <strong>1–4</strong>
              <span>PER TEAM</span>
            </div>
          </div>
        </div>

        <div className="hero-stage" aria-label="WCC Launchpad launch control">
          <div className="stage-label">READY FOR LIFTOFF</div>
          <div className="orbit orbit-one" aria-hidden="true" />
          <div className="orbit orbit-two" aria-hidden="true" />
          <img src={rocket} alt="WCC Launchpad rocket lifting off" className="mascot" width={1024} height={1024} />
          <div className="player-card">
            <span>LAUNCH WINDOW</span>
            <strong>30H</strong>
            <div className="mini-bars">
              <i />
              <i />
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="status-card">
            <span className="live-dot" /> {eventsQ.data && !anyOpen ? "SUBMISSIONS CLOSED" : "REGISTRATION OPEN"}
          </div>
          <div className="xp-card">
            <span>THE OPPORTUNITY</span>
            <strong>100+ WINNERS</strong>
          </div>
          <div className="code-sticker">
            <Rocket size={24} />
            <span>
              TAKE
              <br />
              OFF
            </span>
          </div>
        </div>
      </section>

      <div className="ticker" aria-hidden="true">
        <div>
          SHOW IT WORKS <Sparkles /> TAKE OFF <Sparkles /> FIND YOUR PROBLEM <Sparkles /> BUILD THE ONE FLOW <Sparkles /> SHOW IT
          WORKS
        </div>
      </div>

      <section className="events-section section-pad" id="events">
        <div className="section-heading dark-heading">
          <div>
            <span className="kicker">// CHOOSE YOUR DIRECTION</span>
            <h2>
              THREE WAYS
              <br />
              TO TAKE OFF.
            </h2>
          </div>
          <p>
            Pick a starting point, then make it yours. The strongest build is not the biggest; it is the clearest proof
            that your idea can work.
          </p>
        </div>
        <div className="event-grid">
          {eventCards.map((event, index) => {
            const Icon = event.icon;
            return (
              <article className={`event-card event-card--${event.tone}`} key={event.title}>
                <div className="event-top">
                  <span>TRACK / 0{index + 1}</span>
                  <span className="live-badge">
                    <i /> {!eventsQ.data ? (index === 0 ? "LIVE" : "UPCOMING") : anyOpen ? "LIVE" : "CLOSED"}
                  </span>
                </div>
                <div className="event-icon">
                  <Icon size={42} strokeWidth={2.4} />
                </div>
                <p>{event.track}</p>
                <h3>{event.title}</h3>
                <div className="event-meta">
                  <span>
                    <CalendarDays size={15} /> {event.date}
                  </span>
                  <span>
                    <Users size={15} /> {event.players}
                  </span>
                  <span>
                    <Trophy size={15} /> {event.prize}
                  </span>
                </div>
                <button type="button" onClick={() => join(640)}>
                  JOIN THIS TRACK <ArrowRight size={18} />
                </button>
              </article>
            );
          })}
        </div>
      </section>

      <section className="mission-section section-pad" id="missions">
        <div className="section-heading light-heading">
          <div>
            <span className="kicker">// THE BUILD PATH</span>
            <h2>
              FROM IDEA
              <br />
              TO LIFTOFF.
            </h2>
          </div>
          <div className="mission-status">
            <span>LAUNCH PROGRESS</span>
            <strong>{String(activeLevel + 1).padStart(2, "0")} / 06</strong>
            <div>
              <i style={{ width: `${Math.round(((activeLevel + 1) / levels.length) * 100)}%` }} />
            </div>
          </div>
        </div>
        <div className="level-map">
          {levels.map((level, index) => {
            const Icon = level.icon;
            const selected = activeLevel === index;
            return (
              <button
                type="button"
                key={level.n}
                className={`level-node ${selected ? "level-node--active" : ""}`}
                onClick={() => {
                  setActiveLevel(index);
                  play(500 + index * 35);
                }}
                aria-pressed={selected}
              >
                <span className="level-number">LVL {level.n}</span>
                <span className="level-icon">
                  <Icon />
                </span>
                <strong>{level.label}</strong>
                <small>{level.detail}</small>
                {index < levels.length - 1 && <ChevronRight className="level-arrow" />}
              </button>
            );
          })}
        </div>
        <div className="mission-console">
          <div className="console-copy">
            <span className="console-step">CURRENT OBJECTIVE</span>
            <h3>{levels[activeLevel]?.label ?? "BUILD"}</h3>
            <p>
              {levels[activeLevel]?.detail ?? "Complete the current objective"}. Complete the objective to bank 1,200 XP and
              unlock the next checkpoint.
            </p>
          </div>
          <div className="quest-reward">
            <Award />
            <div>
              <span>THE FINISH LINE</span>
              <strong>₹50,000</strong>
            </div>
          </div>
          <ArcadeButton
            onClick={() => {
              play(780);
              navigate(levels[activeLevel]?.to ?? "/register");
            }}
          >
            {activeLevel === 0 ? "JOIN THE BUILD" : `GO TO ${levels[activeLevel]?.label ?? "BUILD"}`} <ArrowRight size={18} />
          </ArcadeButton>
        </div>
      </section>

      <section className="judging-section section-pad" id="judging">
        <div className="judge-copy">
          <span className="kicker">// WHAT MATTERS</span>
          <h2>
            MAKE IT WORK.
            <br />
            <em>MAKE IT CLEAR.</em>
          </h2>
          <p>
            Build a small, reliable product with one journey that works end to end. Judges look at innovation, execution,
            impact and presentation.
          </p>
          <div className="trust-row">
            <ShieldCheck />
            <div>
              <strong>A FAIR SHOT FOR EVERY TEAM</strong>
              <span>Judges never see each other's scores</span>
            </div>
          </div>
        </div>
        <div className="score-console">
          <div className="console-head">
            <span>JUDGING_ENGINE.EXE</span>
            <span>
              <i /> RUNNING
            </span>
          </div>
          <div className="submission-chip">
            <span>SUBMISSION #082</span>
            <strong>NEURAL GARDEN</strong>
            <small>TEAM NULL POINTERS</small>
          </div>
          <div className="criteria-list">
            {[
              { name: "INNOVATION", score: 94, color: "cyan" },
              { name: "TECHNICAL", score: 89, color: "yellow" },
              { name: "IMPACT", score: 92, color: "coral" },
            ].map((item) => (
              <div className="criteria" key={item.name}>
                <div>
                  <span>{item.name}</span>
                  <strong>{item.score}</strong>
                </div>
                <div className="criteria-track">
                  <i className={`score-${item.color}`} style={{ width: `${item.score}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="final-score">
            <span>NORMALIZED LAUNCH</span>
            <strong>91.7</strong>
            <small>/100</small>
          </div>
        </div>
      </section>

      <section className="rankings-section section-pad" id="rankings">
        <div className="section-heading light-heading">
          <div>
            <span className="kicker">{results ? `// FINAL STANDINGS · ${results.event_name.toUpperCase()}` : "// SAMPLE SCOREBOARD"}</span>
            <h2>
              BUILT TO
              <br />
              GO FURTHER.
            </h2>
          </div>
          <p>
            {results ? (
              <>
                Ranked by normalized judge scores (fair to harsh and generous judges alike), published{" "}
                {fmtDay(results.published_at)}.{" "}
                <Link to={`/results/${results.event_id}`} style={{ color: "inherit", fontWeight: 700, whiteSpace: "nowrap" }}>
                  See the full results →
                </Link>
              </>
            ) : (
              <>
                Example teams and scores are shown as a preview. Real standings appear after judging is complete.{" "}
                <Link to="/gallery" style={{ color: "inherit", fontWeight: 700, whiteSpace: "nowrap" }}>
                  Browse the builds →
                </Link>
              </>
            )}
          </p>
        </div>
        <div className="leaderboard">
          {rows.map((team) => (
            <div className={`team-row team-row--${team.rank}`} key={team.rank + team.name}>
              <span className="rank">{team.rank}</span>
              <span className="team-avatar">{team.badge}</span>
              <div className="team-name">
                <strong>{team.name}</strong>
                <span>{team.build}</span>
              </div>
              <div className="xp-track">
                <i style={{ width: `${team.pct}%` }} />
              </div>
              <strong className="team-xp">
                {team.score} <small>{team.unit}</small>
              </strong>
            </div>
          ))}
        </div>
      </section>

      <footer>
        <div className="footer-lockup">
          <span className="brand-mark">
            <span>W</span>
          </span>
          <h2>
            YOUR IDEA.
            <br />
            <em>YOUR LAUNCH.</em>
          </h2>
        </div>
        <ArcadeButton onClick={() => join(820)}>
          GET ON THE PAD <Swords size={20} />
        </ArcadeButton>
        <div className="footer-bottom">
          <span>© 2026 WCC LAUNCHPAD 30</span>
          <span>4–5 OCTOBER · ONLINE</span>
          <span>BUILT FOR THE BUILDERS</span>
        </div>
      </footer>
    </main>
  );
}
