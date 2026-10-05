# WCC Launchpad

**Automated, provably fair hackathon operations, on one command.**

WCC Launchpad runs a hackathon end to end: registration, teams, submissions,
judging, community voting, results and verifiable certificates. It automates
the repetitive organizer work, and it checks the judging itself before any
result goes public.

Built for **WCC Launchpad 30** (Open Innovation track).

**Live demo:** https://3-104-145-47.sslip.io

> Demo logins (password `DemoPass123!`): `organizer@launchpad.example`,
> `judge_a@launchpad.example`, `judge_b@launchpad.example`,
> `participant@launchpad.example`. The demo is preloaded with a sample event
> (41 projects, 30 judges) so every feature has data to show.

---

## Why WCC needs this

WCC Launchpad 30 is thirty hours, three tracks and teams from across the
country. And the winners go well beyond a top three: track awards, sponsor
challenges, mini-challenges, more than a hundred winners, and a verifiable
certificate for every participant. That means:

- **Thousands of emails**: invites, receipts, reminders, results and
  certificates.
- **Hundreds of judge assignments**, balanced by workload and expertise,
  with conflicts of interest kept out.
- **One hard question:** was the judging fair? Harsh and generous judges,
  copied code, ballot stuffing.

Spreadsheets and group chats can't answer that last question. WCC Launchpad
does, and it shows its evidence.

## What it does

### Event setup
- Organizers create events with **tracks**, **prizes**, and one or more
  **rounds**, each with its own deadline and submission rules.
- A **weighted judging rubric** per event: each criterion and its weight.
- **Invite-only staff roles:** judges and organizers sign up with an invite
  code, which can be emailed straight from the console; participants sign up
  freely.

### Teams and submissions
- **Teams of 1–4**, joined with a team code or an **email invite** whose link
  fills in the code automatically.
- **Submissions** with title, summary, tech stack, repository, demo video and
  file uploads (checked by type, content and size). They can be edited until
  the deadline, which the server enforces.
- **A public gallery** of submitted builds, with no sign-in required.
- **Rounds:** close a round early, extend it for everyone or for a single
  team, advance the top teams to the next round, and let deadlines close
  themselves automatically.

### Fair judging
- **Auto-balancing judge assignment.** An optimal matching (the Hungarian
  method) balances workload, prefers judges who know each track, and never
  assigns a judge to their own team or a declared conflict. The preview is
  exactly what gets saved.
- **Complete judge isolation:** a judge can never see another judge's scores,
  and the server refuses the request outright.
- **Scoring opens only after a round closes**, so judges never score work
  that can still change.
- **Two rankings side by side:** per-judge normalization (fair to harsh and
  generous judges), and a Bradley–Terry model built from **head-to-head**
  comparisons. See `NORMALIZATION.md` and `JUDGING.md`.
- **Scoring health check:** flags judges who give everyone the same score,
  score far from their co-judges, or rank projects opposite to their peers,
  and shows whether a single judge could change the top three.

### Community voting
- **Access:** signed-in voters only, an email allowlist, or an open link.
- **Single-choice or quadratic voting**, where voters spread credits across
  favourites.
- **A shuffled ballot for every voter**, results hidden until published, and
  rate limiting plus shared-address detection against ballot stuffing.
- **Moderated comments** on the gallery.

### Trust and integrity
- **A tamper-evident audit trail.** Every action is cryptographically chained
  to the one before it, so editing history, even directly in the database,
  breaks the chain and shows exactly where. The chain's fingerprint is
  published on the results page.
- **Duplicate detection:** shared repositories or links, and near-identical
  descriptions, while ignoring common boilerplate.
- **The code check** reads every GitHub repository and compares the code
  itself. Renamed variables don't hide a copy (MOSS-style fingerprinting). It
  also flags forks and code committed before the event started.
- **Flags, never verdicts.** Nothing is blocked or penalised automatically,
  and every flag shows its evidence.

### Automation
- **Emails that send themselves:**
  - a welcome on sign-up
  - team and judge invites
  - submission receipts
  - "you've been assigned" and "scoring is open" for judges
  - deadline extensions
  - results
  - certificates, with the PDF attached

  Emails are delivered through SendGrid or any SMTP server, with automatic
  retries.
- **Deadline reminders go only to teams that haven't submitted**, once per
  reminder window.
- **People stay in control:** organizers can switch emails off per event,
  and participants can opt out of reminders and updates.
- **Certificates** for participants, winners and judges, each with a unique
  code and signature. Anyone can verify one at a public link, and revoking
  one takes effect instantly.

### Platform and integrations
- **Every UI action is an API call.** Interactive docs are at `/api/docs`.
- **Event-scoped API keys**, read-only or read/write, stored hashed.
- **Signed webhooks** with retries, a delivery log and SSRF protection.
- **Bulk CSV import** with a row-by-row dry run, and exports that load
  straight back in.
- **Live updates over WebSockets**, which work across several backend
  workers.

## Run it locally

You need Docker. One command:

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:8080**. The first start seeds the demo event and
prints the demo logins and invite codes:

```bash
docker compose logs backend | grep -A 12 "demo accounts"
```

Everything runs on your machine, with no cloud database or hosted service.
Two optional features use the internet:

- **Email:** set `SENDGRID_API_KEY` and a verified `MAIL_FROM` in `.env`, or
  the `SMTP_*` settings. Until then, emails are recorded in the organizer's
  Notifications tab but not sent. Demo addresses are never emailed.
- **Code check:** set `GITHUB_TOKEN`. A token with no permissions is enough.

## Deploy to a public URL

One script on any Ubuntu server: automatic HTTPS, strong secrets and a
firewall. The live demo runs on AWS EC2. See **`DEPLOY.md`**.

## Documentation

| File | What's in it |
|---|---|
| `LAUNCHPAD.md` | How the automation and integrity features work, and what was built during WCC Launchpad 30 |
| `JUDGING.md` | Assignment, scoring, judge isolation, conflicts of interest, pairwise mode |
| `NORMALIZATION.md` | The normalization method, with a worked example on real data |
| `ARCHITECTURE.md` | System design and the reasons behind it |
| `DATA-MODEL.md` | Every table, plus the import and export paths |
| `INTEGRATIONS.md` | API keys, webhooks, certificates, CSV import/export, audit chain |
| `THREAT-MODEL.md` | Attacks considered (ballot stuffing, Sybil voting, copying, collusion) and honest limits |
| `DEPLOY.md` | Putting it online with HTTPS |

## Tech stack

FastAPI (Python), PostgreSQL 16, Redis, React 19 + Vite + TypeScript, Nginx,
Caddy (production HTTPS) and Docker Compose. NumPy and SciPy power the
assignment and statistics. No AI model is called at runtime: every result
traces back to a rule or a formula.

## Known limitations

- No password reset, email verification or 2FA yet.
- The code check reads public GitHub repositories only. Without
  `GITHUB_TOKEN`, it covers about 15 repositories an hour.
- Uploads are validated but not malware-scanned.
- Schema changes need `docker compose down -v` (there are no migrations yet).
- `JWT_SECRET` also signs certificates: changing it invalidates every issued
  certificate.
- The demo accounts use a published password. Wipe the demo data before a
  real event.
- The development test scripts aren't packaged in this repository yet.

## Troubleshooting

- **"column X does not exist":** the database predates a schema change. Run
  `docker compose down -v`, then `docker compose up --build`. This deletes
  local data.
- **Port 8080 in use:** set `HOST_PORT=8090` in `.env`.
- **Emails not sending:** open Organizer → Notifications. The Delivery box
  shows what's missing, and each email shows its exact error. Then check
  `docker compose logs backend | grep MAIL`.

## License

MIT. See `LICENSE`.
