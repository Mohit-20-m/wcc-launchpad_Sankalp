# Architecture

How WCC Launchpad is put together and why. For the features themselves,
see `README.md`; for the judging maths, see `JUDGING.md` and
`NORMALIZATION.md`.

## System overview

```
Browser
  │
  ▼
Caddy (production only: automatic HTTPS on 443, see DEPLOY.md)
  │
  ▼
Nginx (the only app container exposed; port 8080, localhost-only in production)
  ├── serves the built React app
  ├── proxies /api/* → backend:8000
  └── proxies /ws/*  → backend:8000 (WebSocket upgrade)
  │
  ▼
FastAPI backend (internal only, no host port exposed)
  ├── Postgres (internal only)
  ├── Redis (internal only)
  └── outbound, optional: SendGrid/SMTP (email), GitHub API (code check)
```

Only Nginx is reachable from outside Docker. This is deliberate: it keeps
one single entry point and matches how the platform would actually be
exposed in a real deployment.

## Why these tools

Summary of the main choices:

| Layer | Tool | One-line reason |
|---|---|---|
| Backend | FastAPI | async, native WebSockets, free OpenAPI docs |
| Database | PostgreSQL | correctness under concurrent judge writes |
| Frontend | React 19 + Vite + TypeScript, plain CSS | the WCC Launchpad arcade design system; fonts self-hosted via npm so it works offline |
| Auth | Hand-rolled JWT | must be explainable/defensible, not a black box |
| Real-time | WebSockets + Redis pub/sub | live counters, announcements |
| Reverse proxy | Nginx (+ Caddy in production) | Nginx works offline for local use; Caddy is added only in production for automatic HTTPS |
| Email | SendGrid API or any SMTP | transactional outbox, so email never blocks or loses an action |
| Scientific | NumPy + SciPy | optimal judge assignment (Hungarian method) and score statistics |

## Table creation and schema drift (a real bug we hit)

Tables are created from the SQLAlchemy models on backend startup
(`Base.metadata.create_all`) rather than through Alembic migrations —
a documented speed tradeoff for the 72-hour build. The real
consequence, which we hit for real during development: `create_all`
only creates tables that don't exist yet, it never alters an existing
one. When `invite_code` was added to the `Team` model after the table
had already been created once, inserts started failing with
`UndefinedColumnError` until the Postgres volume was wiped
(`docker compose down -v`) so the table could be recreated with the
current schema. See `README.md`'s Troubleshooting section for the fix;
noting the failure mode here too since it's an architectural
consequence of the tradeoff, not just a one-off bug.

## Backend at a glance

| Area | Where |
|---|---|
| Auth, roles, invites | `core/security.py`, `api/routes/auth.py`, `api/routes/invites.py` |
| Events, rounds, teams, submissions | `api/routes/events.py`, `rounds.py`, `teams.py`, `projects.py`, `services/rounds.py` |
| Judging, normalization, pairwise | `api/routes/judging.py`, `pairwise.py`, `services/normalization.py`, `bradley_terry.py`, `judging_rules.py` |
| Auto-assignment | `services/assignment.py` |
| Scoring health check | `services/anomaly.py` |
| Voting, comments, rate limits | `api/routes/voting.py`, `comments.py`, `services/voting.py`, `ratelimit.py` |
| Audit chain, duplicate detection | `services/audit.py`, `services/similarity.py`, `api/routes/integrity.py` |
| Code check (GitHub) | `services/codescan.py` |
| Email notifications | `services/mailer.py` |
| Webhooks, API keys, certificates, import/export | `services/webhooks.py`, `api/routes/api_keys.py`, `services/certificates.py`, `services/importer.py`, `api/routes/data_io.py` |
| Organizer routes for the automation and integrity tools | `api/routes/engage.py` |

**One background loop** (`services/webhooks.py`, the dispatcher) delivers
webhooks, sends due emails, sweeps round deadlines and runs the deadline
reminders. Each job claims its work atomically, so several backend workers
never do the same job twice.

## Role enforcement

Implemented in `backend/app/core/security.py`. Every protected route
depends on `require_role(...)`, which:

1. Reads the `Authorization: Bearer <token>` header
2. Decodes and verifies the JWT (signature + expiry)
3. Loads the corresponding user from the database
4. Checks the user's role against the route's allowed roles
5. Raises 401 (not authenticated) or 403 (wrong role) at the API layer —
   never relies on the frontend hiding a button

This is the same guard every future protected route reuses, including
the judge-privacy checks that the test suite verifies.

Verified end-to-end with a real request-level test (register → duplicate
rejection → login → wrong password rejection → token validation →
missing/garbage token rejection), not just unit-tested in isolation.

## Frontend structure

- `src/pages/` public pages (Landing, Login, Register, Gallery, NotFound);
  `src/pages/console/` the three role consoles sharing `ConsoleShell`.
- `src/api/client.ts` is the only place that talks to the backend: typed
  calls, FastAPI error messages surfaced, a 401 clears the session.
- `RequireRole` guards routes for convenience only; the backend re-checks
  the role on every request (`require_role`).
- The active console tab lives in the URL (`?tab=`), so refresh and links work.
- One design system, `src/styles.css` (the WCC Launchpad look), shared by
  the landing page, the public pages and all three consoles.


## Platform layer: webhooks, API keys, certificates, import/export

**One source of events.** Webhooks are driven by the audit trail: `audit()` is
already called for every action worth recording, in the caller's transaction.
It now also writes a `webhook_deliveries` row for each subscribed endpoint, so
"what gets announced" equals "what gets audited", and an event is queued only
if the action committed (a transactional outbox). A background dispatcher (a
task in the app's lifespan) claims due deliveries with an atomic update, signs
and POSTs them, and schedules retries; it also notices rounds whose deadline
has passed, since no request happens at that moment.

**Hash-chained audit.** `audit()` reads the event's chain head, computes the
row hash, and advances the head with `UPDATE … WHERE seq = <what I read>`.
If another request won the race the update matches nothing and it re-reads,
so the chain cannot fork under concurrency, on any database, without table locks.

**API keys reuse the one auth door.** `get_current_user` accepts either a JWT
or a `dgf_` key. A key resolves to its organizer plus two transient markers
(its event and scope). `get_owned_event`, through which every organizer route
already passes, refuses any other event; the read scope refuses non-GET; a short
list of account-level prefixes is refused outright. There is no second
permission system to keep in sync.

**Import = validate, then apply.** Each importer builds a *plan* (per-row
verdicts) from read-only queries; a dry run returns the plan, a commit applies
it in one transaction.

**New modules:** `models/platform_layer.py`; `services/{webhooks,certificates,similarity,importer}.py`;
`api/routes/{api_keys,webhooks,certificates,data_io,integrity}.py`.

## Rounds, voting and live updates

### Rounds and the scoring gate
An event has numbered **rounds**, each with its own deadline and its own rules
about what a team may submit (idea text, repo link, video link, files with
allowed types and a size cap) and who may enter (everyone, or only teams the
organizer advances). Round state is *derived*: `open` between `opens_at` and
`closes_at`, and `closed` once the deadline passes **or** the organizer closes it early.
Extending a deadline (for everyone, or for one team) and reopening a closed
round are explicit, audited actions.

The rule that ties judging to this is in one place, `services/judging_rules.py`:
**a judge may score a project only when its submissions are closed** (deadline
passed *or* closed early, and no extension still open for that team) **and**
the judge has no conflict on it. Scoring, head-to-head comparison and the
judge queue's `scorable` flag all call it, so the UI and the API cannot drift.

### Who owns what
Every event has an `owner_id`. `core/ownership.py` is the single door: every
event-scoped route resolves its event through `get_owned_event`, so another
organizer gets `403`, and admins see everything. Exports are per event.

### Voting
`routes/voting.py` handles three identity modes (signed-in, email allow-list,
open link) and two methods (one vote per project, quadratic). The server
shuffles the ballot per voter, validates costs, rate-limits, flags shared
addresses and hides results until publish. `THREAT-MODEL.md` lists each
defence and its limits.

### Live updates (WebSockets)
`/ws/live/{event_id}` pushes *refresh signals*, never data: a message is
`{"type":"refresh","topics":["stats", ...]}` and the browser then refetches
through the normal REST API, which enforces permissions. With several workers,
`services/live.py` bridges instances through Redis pub/sub, and organizer-only
topics (`stats`, `submissions`, `progress`, `audit`, ...) are filtered
**per connection** from the optional `?token=`. If a socket cannot connect the
pages still refresh by slow polling.

### Redis is optional at runtime
`services/redis_client.py` degrades to in-memory rate limiting and
single-process live updates if Redis is unreachable, retrying with backoff, so
a Redis blip never takes the site down.

### Files
`services/files.py` validates the extension, the leading bytes, and the size
(while streaming), stores under a random name in the `uploads_data` volume,
and downloads go through an authenticated endpoint. Replacing a submission
deletes its files from disk.

### Registration
Judges and organizers register with an **invite code** (`role_invites`); the
first codes are created at boot and printed in the log banner.

## Automation and integrity

Email notifications, auto-assignment, the scoring health check and the code
check are documented in depth in `LAUNCHPAD.md`. Architecturally:

- **Email** uses the same transactional outbox as webhooks: `audit()` queues
  the email inside the action's own transaction, and the background loop
  sends it with retries.
- **Auto-assignment and the health check** are pure functions over data
  loaded by the route. They're deterministic, which is why a preview always
  matches the saved result.
- **The code check** runs as a background task per event. It stores only
  token fingerprints, never source code, and it never blocks a submission.

## Production

`docker-compose.prod.yml` adds Caddy in front of Nginx. Nginx trusts
`X-Forwarded-For` only from private addresses, so the backend sees each
visitor's real IP. Voting rate limits and shared-address detection depend
on this, and a visitor can't fake a new IP per vote. See `DEPLOY.md`.
