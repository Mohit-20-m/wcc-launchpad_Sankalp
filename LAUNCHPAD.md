# Built for WCC Launchpad 30

This document covers what was built during **WCC Launchpad 30**, how each
piece works, and how to try it.

## Disclosure: what existed before the event

The base of this project is a hackathon submission and judging platform our
team built earlier, for a previous hackathon (September 25–28, 2026).
Everything in that base was written before WCC Launchpad 30 started, including accounts and roles, events, teams, submissions, judging
with normalization and pairwise mode, voting, certificates, webhooks, API keys,
CSV import/export, the hash-chained audit trail and text-based duplicate
detection.

**Built during WCC Launchpad 30** (Oct 4–5, 2026), listed below:

| Feature | Backend | Frontend |
|---|---|---|
| Automated email notifications | `services/mailer.py`, `api/routes/engage.py` | `organizer/NotificationsTab.tsx`, `components/EmailTools.tsx` |
| Certificate delivery by email | `services/mailer.py`, `api/routes/certificates.py` (send_email) | `organizer/CertificatesTab.tsx` |
| Deadline reminders for teams that haven't submitted | `services/mailer.py` (`sweep_reminders`) | Notifications tab |
| Auto-balancing judge assignment | `services/assignment.py` | `organizer/AutoAssignPanel.tsx` |
| Judge score anomaly detection | `services/anomaly.py` | `organizer/AnomalyPanel.tsx` |
| Code-level duplicate detection and repository timeline | `services/codescan.py` | `organizer/CodeScanPanel.tsx` |
| New tables | `models/engage.py` | |
| Welcome email on registration | `services/mailer.py` (`queue_welcome`), `api/routes/auth.py` | |
| Team invites and judge invites by email (links pre-fill the code) | `api/routes/engage.py` | `components/EmailTools.tsx`, `organizer/JudgesExtras.tsx`, `pages/Register.tsx` |
| Participant email preferences | `models/engage.py`, `api/routes/engage.py` | `components/EmailTools.tsx` |
| Email settings (SendGrid / SMTP), demo accounts never emailed | `services/mailer.py`, `docker-compose.yml`, `.env.example` | Notifications tab |
| The WCC Launchpad UI: landing page, sign-in, consoles, live scoreboard, progress-based player level; React 19 | | `styles.css`, `pages/Landing.tsx`, `pages/Login.tsx`, `components/*` |
| Production deployment: automatic HTTPS, real-visitor-IP handling for vote rate limits, one-command server setup | `nginx/nginx.conf`, `docker-compose.prod.yml`, `deploy/` | |

AI coding assistants were used during development. No feature calls an AI
model at runtime: every result can be traced to a rule or a formula.

## The problem these solve

Running a hackathon is mostly manual follow-up and judgment calls made without
evidence. Organizers chase teams that haven't submitted and assign judges by
hand. They email certificates one at a time, and they find out about a copied
project or a judge who scored everything a "4" only after results are public.
Platforms like Unstop and Devfolio handle registration and submission well,
but they leave fairness checks to the organizer.

The theme of these additions is **automated, provably fair hackathon
operations**:

- **Automation** takes repetitive work off organizers: notifications,
  reminders, certificate delivery and assignment.
- **Fairness tools** give organizers evidence before they publish: balanced
  conflict-free assignment, scoring anomalies and copied-code detection.
- **The existing audit trail** records every action, so all of it is
  tamper-evident.

## 1. Email notifications

**Who gets told what, automatically:**

| Trigger | Recipients | Email |
|---|---|---|
| New registration | the new user | welcome, worded for their role |
| Team created | creator | team code and how to invite |
| Teammate joins | other members | who joined |
| "Invite by email" | invitee | code plus a link that pre-fills it |
| Submission or resubmission | all team members | receipt with time and edit deadline |
| Judge assigned (manual) | judge | what to review, conflict-of-interest reminder |
| Auto-assignment | each judge, **once** | list of all their projects |
| Judge invite code emailed | invitee | code plus a sign-up link that pre-fills it |
| Round closes (deadline or early) | judges with work in that round | "scoring is open" |
| Team extension granted | team members | new deadline and reason |
| Deadline approaching, no submission yet | that team only | reminder |
| Results published | all participants and judges | link to results |
| Certificate issued | recipient | **PDF attached**, verification link |

**How it works.** It uses the same transactional-outbox design as the existing
webhooks. `audit()` already runs for every meaningful action, inside that
action's database transaction, and it now also calls
`mailer.enqueue_for_action`. An email row is therefore committed only if the
action committed, and it survives a mail-server outage. A background loop (the
existing webhook dispatcher) sends due emails, retrying after 30 seconds, then
2, 10 and 30 minutes. Each email is claimed atomically, so several workers
never send the same one.

**Reminders** run every minute. For each open round, a team with no
non-draft submission gets one reminder per configured window (default: 24
hours and 3 hours before the deadline). The window is measured against the
team's own deadline if it has an extension. A unique `dedupe_key` per (round,
team, person, deadline, window) makes the sweep idempotent, even with several
workers. Teams with a saved draft are told that submitting it takes one click.

**Control.**
- **Organizers** can switch email, reminders or certificate emails off per
  event, and set the reminder hours.
- **Participants** can switch off reminders and general updates for
  themselves. Receipts, invites, assignments and certificates always arrive.
- **The outbox** (Notifications tab) shows every email with its status, a
  preview, and a retry button for failed ones.

**Providers.**
- `sendgrid` (the default) uses the SendGrid v3 API. Set `SENDGRID_API_KEY`
  (a key with Mail Send permission) and a `MAIL_FROM` address you verified in
  SendGrid.
- `smtp` works with any SMTP server: Gmail with an App Password, SendGrid's
  SMTP relay (username `apikey`), or your host's mail server.
- `disabled` records emails in the outbox without sending them.

Until the chosen provider is configured, emails are recorded as **skipped:
not configured** rather than failing over and over. Once it's set up, press
Retry in the outbox. Each send or failure is also logged as a `MAIL` line in
`docker compose logs backend`.

**Welcome email.** Every new registration gets one, worded for the role:
participants are told how to form a squad, judges that they'll be emailed when
projects are assigned, organizers how to start. It's queued in the same
transaction as the new account, and a problem with email can never block
sign-up.

**Demo accounts are never emailed.** Seeding sends nothing. The fixture's
historical round is marked as already announced, so the deadline sweeper
doesn't announce it on first boot. On top of that, addresses on reserved
domains are always skipped, whatever the configuration: `example.org/.com/.net`
and their subdomains, `*.example`, `*.test`, `*.invalid`, `*.localhost` and
`*.local` (RFC 2606 and RFC 6761). Every demo and fixture account uses one of
these, and mail to them could never be delivered anyway. Add more domains with
`MAIL_SKIP_DOMAINS`.

## 2. Auto-balancing judge assignment

**Goal.** Every project gets *K* reviews. Work is spread evenly across judges,
judges who know a project's track are preferred, and nobody reviews their own
team or a project they declared a conflict on.

**Method: repeated optimal matching.** A single assignment problem can't
require *K* different judges per project, because the solver could give the
same judge the same project twice. So the planner solves *K* rounds. In each
round, every project still short of reviews gets at most one new judge, chosen
by `scipy.optimize.linear_sum_assignment` (the Hungarian method). This finds
the minimum-cost matching, not a greedy one.

Each judge is expanded into slots up to a balanced capacity,
`ceil(total reviews ÷ judges)`. Each slot's cost rises with the judge's load,
so the solver fills the least-loaded judges first. Track expertise adds a
cost:

| Judge's listed expertise | Cost added |
|---|---|
| Includes the project's track | 0 |
| None listed (generalist) | 2 |
| Other tracks only | 6 |

In "strict" mode, a judge without a matching track can't be assigned at all.
Conflicts are forbidden outright. If the pool can't cover a project, it is
reported as short, never given a conflicted judge.

**The preview is the commit.** Inputs are sorted by id, so the plan is
deterministic. Pressing "Apply" re-runs the same computation on the server and
writes exactly what the preview showed, in one transaction. The audit log
records `judge.auto_assign`, and each judge gets one email.

**On the fixture data:** 8 projects had only 2 reviews. With K = 3 the planner
fills exactly those 8, each with a judge who isn't already on that project.

## 3. Judge score anomaly detection

Every check compares a judge with their **co-judges on the same projects**,
using a leave-one-out consensus rather than a global average. That way a judge
who drew a strong batch of projects isn't mislabelled "lenient".

| Check | Rule |
|---|---|
| Same score for all | at least 3 reviews, all with an identical overall score |
| Criteria not separated | at least 80% of reviews give every criterion the same number |
| Consistent offset | average offset from co-judges ≥ 0.75 points **and** \|t\| ≥ 2 across at least 3 projects (normalization already corrects for this; it's shown for information) |
| Outlier score | one review ≥ 1.5 points from the average of at least 2 co-judges |
| Opposite to peers | Spearman rank correlation with co-judge consensus ≤ −0.3, over at least 4 projects |
| Swings the top 3 | recompute the normalized ranking without this judge: does the top 3 change? |

The last check is also summarized for the whole event as "how many single
judges could change the podium". It's a direct measure of whether projects
need more reviews before results are published.

**On the fixture data:** the deliberately flat judge is flagged first ("gave
all 3 projects the same overall score"). The check also finds 7 outlier
scores, 2 judges who rank opposite to their peers, and 8 judges whose removal
would change the top 3. That last number is a real finding: with about 3
reviews per project, the podium is fragile.

Nothing is changed automatically. The panel says so, because these flags are
prompts for a conversation, not verdicts.

## 4. Code-level duplicate detection and repository timeline

The existing detector compares links and descriptions. This one compares
**the code**.

1. **Fetch.** For each GitHub repository it reads the metadata, the latest
   commit, the commit count, and the first and last commit dates. It then
   downloads up to 80 source files at that exact commit, skipping vendored,
   generated, minified and lock files.
2. **Normalize.** Comments and whitespace are removed, and every identifier
   becomes `V`, every string `S` and every number `N`. Keywords and operators
   are kept, so renaming variables or reformatting changes nothing.
3. **Fingerprint** with winnowing, the algorithm behind Stanford's MOSS
   (Schleimer, Wilkerson and Aiken, 2003). It hashes every 12-token window and
   keeps the minimum hash in each window of 8. Any shared run of 19 or more
   tokens is guaranteed to produce a shared fingerprint.
4. **Compare** every pair of repositories from different teams. Fingerprints
   found in many repositories, such as framework starters, are dropped first,
   in the same way the text detector drops boilerplate. A pair is reported
   with its containment (how much of the smaller repository appears in the
   larger one), its Jaccard similarity, and the best-matching file pairs as
   evidence.

**Timeline flags**, using the event's own dates:
- first commit before the event started (WCC's rules require prior work to be
  disclosed)
- latest commit after the deadline (judge the earlier commit)
- the repository is a fork, especially of another team's submission
- the repository has 2 or fewer commits

**Tested on real code:** three unrelated repositories from the same
organization, written in the same style, produced no false positives. A copy
with renamed identifiers was detected at 100% containment, with the matching
files listed.

**Rate limits.** Without `GITHUB_TOKEN`, GitHub allows 60 API calls an hour,
about 15 repositories, since each repository takes 4 calls. A token with no
scopes raises this to 5,000. When the limit is hit, the scan stops and every
remaining project shows "try again after HH:MM". With no network, each
project shows "couldn't reach GitHub". Nothing crashes.

## Data model additions

All changes are **new tables only**. An existing database picks them up on the
next start, with no `docker compose down -v` needed.

| Table | Purpose |
|---|---|
| `email_outbox` | every email: recipient, kind, rendered body, status, attempts, error, dedupe key |
| `mail_settings` | per-event switches and reminder hours |
| `mail_preferences` | per-user opt-outs (reminders, updates) |
| `judge_expertise` | (event, judge, track); seeded from the fixture's judge tracks |
| `repo_scans` | per-project repository facts and code fingerprints (never sent to the browser) |

## API

All endpoints are listed in the interactive docs at `/api/docs`.

| Method | Path | Who |
|---|---|---|
| GET | `/mail/status` | organizer |
| GET, PUT | `/events/{id}/mail/settings` | organizer (owner) |
| GET | `/events/{id}/mail/outbox`, `/events/{id}/mail/outbox/{email}` | organizer (owner) |
| POST | `/events/{id}/mail/outbox/{email}/retry`, `/events/{id}/mail/test`, `/events/{id}/mail/remind-now` | organizer (owner) |
| GET, PUT | `/me/mail-preferences` | any signed-in user |
| POST | `/teams/{id}/invite-email` | team members |
| POST | `/invites/{id}/email` | the organizer who created the invite |
| POST | `/events/{id}/certificates/{cert}/email` | organizer (owner) |
| GET | `/events/{id}/expertise` | organizer (owner) |
| PUT | `/events/{id}/expertise/{judge}` | organizer (owner) |
| POST | `/events/{id}/auto-assign` (`dry_run: true` previews) | organizer (owner) |
| GET | `/events/{id}/anomalies` | organizer (owner) |
| POST, GET | `/events/{id}/code-scan` | organizer (owner) |

Every organizer route goes through the existing `get_owned_event`, so
isolation between organizers and API-key event scoping apply unchanged.

## Verification

Tested against both SQLite and **PostgreSQL 16**:

- **End-to-end API suite (40 checks)** covering:
  - auto-assignment: preview equals commit, no double assignment, permissions
  - anomalies on the fixture data
  - a full event lifecycle that triggers every email type
  - reminder targeting and idempotency
  - per-user opt-out
  - certificate PDFs actually attached in delivered mail
  - organizer isolation
  - graceful code-scan failure
- **Retry under failure:** with the mail server stopped, emails were kept and
  delivered once it came back.
- **Browser smoke test** of every new panel against a production build: the
  auto-assign preview, the email preview, anomaly details, invite links that
  pre-fill codes, and participant preferences.
- **Production chain:** a visitor's real IP survives Caddy → Nginx →
  backend, a forged `X-Forwarded-For` is ignored, and live updates work over
  secure WebSockets.

These tests were run during development; the scripts aren't packaged in the
repository yet.
