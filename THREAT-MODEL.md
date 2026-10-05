# Threat model: community voting and the rest of the public surface

What WCC Launchpad defends, from whom, how, and, just as importantly,
**what it does not defend against**. The last section says how the
mitigations were verified.

## What we are protecting

1. **The integrity of the vote and of the judges' ranking**: results should
   reflect real preferences, not the most determined script.
2. **The confidentiality of unpublished results**: nobody, including
   participants, judges and other organizers, sees standings before the
   organizer publishes them.
3. **Private submission material**: uploaded files are readable only by the
   team, the judges assigned to that project, and the event's organizer.
4. **Voter privacy**: nobody, including organizers, can read a voter's
   email, token or network address back out of the system.
5. **One organizer cannot see or touch another organizer's event.**

## Who might attack, and what they want

| Actor | Goal |
|---|---|
| A team member | Inflate their own project's votes; vote for their own team |
| A script author | Stuff the ballot from one machine (many tokens, one address) |
| A spectator | See the standings early; scrape voter data |
| A hostile participant | Upload something dangerous; read another team's files |
| A curious organizer | Read a rival organizer's event, scores or exports |
| A judge | Score a project they are conflicted on, or before it is final |

## Threats and mitigations

| # | Threat | Mitigation | Where |
|---|---|---|---|
| 1 | Voting for your own team | The server removes your own team's project from your ballot **and** rejects a ballot that includes it. Enforced only where identity is known (signed-in accounts). | `services/voting.py`, `routes/voting.py` |
| 2 | Double voting | One ballot per voter identity; re-voting **replaces** the earlier ballot, so counts never stack. Identity is a salted SHA-256 of the account id, the lower-cased email, or the browser token, depending on the mode. | `services/voting.py` |
| 3 | Ballot-stuffing by a script | Sliding-window rate limits: **10 ballot attempts / 60 s per voter** and **20 / 60 s per network address**; excess gets `429` and is written to the audit log (`vote.rate_limited`). | `routes/voting.py`, `services/ratelimit.py` |
| 4 | Many fake identities behind one address | Ballots record a **hash** of the address. When **4 or more different voters** share one address, the ballot is flagged (`vote.flagged_shared_ip`) and shown in the organizer's ballot review with a Void button. Voided ballots stop counting immediately and the voter cannot simply vote again; a void can be restored. We flag instead of auto-rejecting so a shared school or campus network is not silently disenfranchised. | `routes/voting.py` |
| 5 | Quadratic-vote gaming | The server recomputes the cost (n votes cost n²), refuses anything over the credit budget, and counts **votes**, not credits. Method, limits and round lock once the first ballot exists so rules cannot change under voters' feet. | `services/voting.py` |
| 6 | "Position bias" and manipulation of order | The ballot order is shuffled **per voter, by the server**, deterministically (same voter, same order on refresh), so nothing wins by being listed first and the shuffle cannot be defeated by re-rolling. | `services/voting.py` |
| 7 | Seeing standings early | Vote tallies and the published ranking return `403` to everyone but the event's organizer until they publish. Ballot responses never contain counts. Live-update messages carry only topic names, never data. | `routes/voting.py`, `routes/publish.py`, `services/live.py` |
| 8 | Voting outside the window | Open/close times are compared against the **server clock**; a closed or not-yet-open ballot returns `409`. | `services/voting.py` |
| 9 | Comment spam | Sign-in required, **5 comments / minute and 60 / day per account**, 1,000-character cap, and the event's organizer can hide (and unhide) a comment. | `routes/comments.py` |
| 10 | Malicious uploads | Extension allow-list (no executables), the **file's first bytes must match its extension** (a renamed `.exe` fails), per-round type list and size cap (hard ceiling 50 MB, enforced while streaming so a huge body is not buffered), random stored names (a client filename is never used as a path, so `../../etc/passwd` is harmless), and downloads are served as attachments with `nosniff` and `no-store`. | `services/files.py`, `routes/projects.py` |
| 11 | Reading someone else's files | Download/delete require being on the team, or an **assigned, non-conflicted judge**, or the event's organizer. Everyone else gets `401/403`. | `routes/projects.py` |
| 12 | Organizer reads another organizer's event | Every event-scoped route resolves the event through an **ownership check**; the event list for organizers contains only their own; exports are per event and refuse events you do not own. | `core/ownership.py` |
| 13 | Spreadsheet formula injection via CSV | Any cell starting with `=`, `+`, `-`, `@` is prefixed so Excel/Sheets treat it as text. | `services/csvsafe.py` |
| 14 | Privilege self-escalation at sign-up | Judge and organizer accounts need an **invite code** of that exact role (single- or multi-use, expiring, revocable); admin can never self-register; only an admin can mint organizer invites. | `routes/auth.py`, `routes/invites.py` |
| 15 | Judge scoring unfinished or conflicted work | The **scoring gate**: scores and head-to-head are accepted only after the round's submissions close, and never on a project the judge declared a conflict on or that is their own team's. | `services/judging_rules.py` |
| 16 | Tampering that leaves no trace | Organizer actions and integrity events go to an **append-only audit log** (readable and exportable in the UI). Voter identities in it are hashed. | `services/audit.py` |
| 17 | Double-submit races | Submission takes a row lock on the team, so two simultaneous clicks cannot create two submissions for one round. | `routes/projects.py` |

## Platform layer: API keys, webhooks, certificates, audit chain

| Surface | Threat | Mitigation |
|---|---|---|
| Webhook URLs | **SSRF**: aiming the platform at its own network or cloud metadata | scheme must be http(s); no credentials in URLs; every resolved address must be public (private, loopback, link-local, multicast, reserved refused); checked at save **and before every send** (DNS rebinding); redirects not followed; 5 s timeout |
| Webhook receivers | forged or replayed requests | HMAC-SHA256 over `timestamp.body` with a per-endpoint secret; receivers reject stale timestamps; `id` allows de-duplication |
| Webhook payloads | leaking personal data | ids and names only: no emails, tokens or secrets |
| Webhook failures | a dead endpoint blocking or being hammered | bounded retries with backoff; auto-pause after 10 exhausted deliveries |
| API keys | theft or over-reach | one event only; read/write scope; cannot create events, invites or keys; SHA-256 at rest; shown once; expiry and instant revocation |
| Certificates | forging or altering | HMAC over the contents; a database edit fails verification and blocks the PDF; revocation |
| Certificate codes | guessing | ~60 bits; public lookups rate-limited per address |
| Audit trail | silent edits or deletions | hash chain: any edit, reorder or deletion is detected and pinpointed |
| Bulk import | bad or hostile files | 2 MB / 5,000-row caps, strict UTF-8, per-row validation, all-or-nothing by default, formula-safe export |
| Similarity flags | false accusation | flags only inform an organizer; nothing is blocked or penalised; boilerplate and titles are ignored |

Limits specific to this layer:
- **The audit chain is tamper-*evident*, not tamper-proof.** Someone who can write to the database can recompute the chain from the point they changed. The public anchor helps only if its hash was copied somewhere the organizer does not control.
- **Webhook secrets are stored readable** (the server must sign with them). Anyone with database access can read them; rotate after any suspected exposure.
- **A write API key is as powerful as the organizer within its event**, including destructive actions. Treat it like a password.
- **Certificates depend on `JWT_SECRET`.** Anyone who has it can forge certificates, and changing it invalidates all existing ones.
- **Webhook errors reveal reachability.** For public hosts, the delivery log shows HTTP status and errors, which lets an organizer probe what a public URL answers. It cannot reach private addresses.
- **Import bypasses round deadlines** (it is the organizer's authority) and can create accounts with one-time passwords the organizer must distribute safely.
- **Duplicate detection is heuristic**: rewording defeats it; coincidence can trigger it.

## Automation and integrity features

- **Email used as a spam cannon.** Only organizers can send test emails, and
  only for events they own. Team invites can only be sent by team members,
  20 addresses at most per request, and the same invite to the same address
  is deduplicated within an hour. Demo and reserved domains are never
  emailed.
- **Reminder floods.** Each reminder has a unique key (round, team, person,
  deadline, window), so the sweep is idempotent even with several workers.
  Participants can switch off reminders and updates.
- **Email failure blocking actions.** It can't: emails are queued in an
  outbox inside the action's transaction and sent later, so a mail outage
  never fails a submission or a sign-up.
- **Code-check abuse.** Only github.com repositories are fetched, from a
  fixed host, so the check can't be pointed at internal addresses. Downloads
  are capped by file count and size. Only code fingerprints are stored, never
  source. A `GITHUB_TOKEN` needs no permissions at all.
- **False accusations.** The code check, the duplicate detector and the
  scoring health check only *flag* things for a human. Nothing is blocked,
  penalised or re-ranked automatically, and every flag shows its evidence
  (matching files, commit dates, the statistic behind it).
- **Judge privacy in the health check.** The per-judge statistics are
  organizer-only, the same audience that can already export every score.
- **Gaming auto-assignment.** A judge can't pick their own projects.
  Assignment is computed server-side, conflicts and team membership are hard
  exclusions, and every run is recorded in the audit trail.

## What we do NOT defend against (honest limits)

- **Open-link voting is not identity.** A browser token is a convenience. Someone who clears storage or uses several browsers gets several tokens. The rate limits and address flagging slow and expose this; they do not prevent it. Use signed-in voting when the result matters.
- **Email-gated voting does not verify the email.** The platform is fully offline and sends no mail, so an allowed address is a *gate*, not proof the voter owns it.
- **Own-team voting cannot be caught for anonymous voters**: with no identity, we cannot know whose team they are on.
- **Shared addresses (NAT).** Address flagging can mis-flag a whole campus. That is why it flags for human review instead of rejecting.
- **Address quality depends on the proxy.** We trust `X-Real-IP` set by our own nginx. If the platform is exposed without that proxy, addresses can be spoofed.
- **No malware scanning** of uploads. We check type, size and magic bytes, not contents. Files are never executed or rendered by the server, only stored and served as downloads.
- **Rate limiting without Redis is per-process.** Redis is part of the Compose stack and shared across workers. If it is down the limiter falls back to in-memory, which is still correct for one worker but weaker across several.
- **No 2FA, email verification or password reset**, and no account lockout on repeated failed logins.
- **The seeded demo accounts** use a published password so judges can try every role, and the **bootstrap invite codes** print to the server logs on start. Before a real event, wipe the demo data and create fresh, expiring invites.
- **The code check reads only public GitHub repositories**, and copying from outside the submitted set (e.g. a public tutorial) is only caught if a fork or commit-date flag points to it.

## How the claims were verified

The mitigations were exercised during development with request-level tests
against the running stack, using real HTTP, a real database and a real clock,
on both SQLite and PostgreSQL 16. These covered:

- registration gating
- rate limits (`429` observed)
- shared-address flagging
- quadratic cost maths
- results hidden from every role until published
- file validation and access control
- organizer isolation
- audit-chain tamper detection, by editing the database directly
- webhook signatures and SSRF refusals
- email opt-outs and reminder idempotency
- the real-visitor-IP chain through Caddy and Nginx, including attempts to
  forge `X-Forwarded-For`

The test scripts aren't packaged in this repository yet. That's a known gap,
listed in `README.md`.
