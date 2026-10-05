# Data Model

## Accounts, events, teams and submissions

- `users` — id, email (unique), name, password_hash, role, created_at.
  Role is one of: visitor, participant, judge, organizer, admin.
- `events` — id, name, description, submissions_close, and optional
  starts_at, ends_at, capacity. `status` (upcoming / submissions_open /
  judging) is derived from the dates, never stored. `submissions_close` is
  what the "closed event refuses submissions" rule depends on — it must be honored server-side, not just displayed.
- `tracks` — id, event_id (FK), name
- `prizes` — id, event_id (FK), name, amount
- `teams` — id, event_id (FK), name
- `team_members` — id, team_id (FK), user_id (FK), is_leader
- `projects` — id, team_id (FK), track_id (FK, nullable), title, summary,
  repo_url, tech_stack, video_url, **status** (draft/submitted/locked),
  submitted_at, updated_at

**Deliberate simplification, documented rather than left unexplained:**
the original plan had a separate `submissions` table wrapping each
project (see git history / earlier drafts of this file). We merged
submission lifecycle fields directly onto `Project` instead, because
`fixtures.json` itself models a project as having one `submitted_at`
and one lifecycle — a separate join table would have added complexity
without matching the data we actually need to load. If a project ever
needs multiple submission *versions* (e.g. resubmission history), that's
the natural point to split it back out.

**Table creation strategy:** for the speed of a 72-hour build, tables are
created directly from the SQLAlchemy models on backend startup
(`Base.metadata.create_all`) rather than through hand-authored Alembic
migrations. This is a documented, deliberate tradeoff — see
`backend/alembic/README.md` — not an oversight. Alembic stays wired in
the project for any future schema change if time allows.

## Judging
- `judging_criteria` — id, event_id (FK), name, weight, description (guidance
  shown to judges). Names are matched case-insensitively against score keys. Organizer-configured
  rubric; if empty for an event, all submitted criteria are weighted equally.
- `judge_assignments` — id, event_id (FK), judge_user_id (FK), project_id (FK).
  A judge can only score a project they have a row here for.
- `scores` — id, judge_user_id (FK), project_id (FK), criteria (JSON,
  matching `fixtures.json`'s shape exactly), comment, created_at, updated_at.
  Unique on (judge_user_id, project_id) — resubmitting updates in place
  rather than creating a second row.
- `pairwise_comparisons` — id, event_id (FK), judge_user_id (FK),
  project_a_id (FK), project_b_id (FK), winner_id (FK), created_at.
  **Bonus challenge (Pairwise Mode):** an alternative to the `scores`
  table above — a judge picks a winner between two assigned projects
  instead of giving an absolute score. Ranked via the Bradley-Terry
  estimator in `services/bradley_terry.py`. See `JUDGING.md` §9.

Normalization and weighted-score combination are computed on demand in
`backend/app/services/normalization.py`, not stored — see `JUDGING.md` for
the method and why.

## Announcements and event details
- `announcements` — id, event_id (FK, nullable = all events), author_id (FK),
  body, created_at. Organizer posts; anyone can read.

## Rounds, voting, files and safety

**Rounds**
- `rounds`: id, event_id, number, name, instructions, opens_at, closes_at,
  closed_early_at, `allow_idea/repo/video/files`, file_types (JSON),
  max_file_mb, open_to_all. An event with no explicit rounds gets an implicit
  Round 1 that allows everything. State (`not_open`/`open`/`closed`) is
  **computed** from the clock and `closed_early_at`, never stored.
- `round_advancements`: (round_id, team_id). Who may enter a round that is not
  `open_to_all`.
- `team_extensions`: (round_id, team_id, closes_at, reason). Extra time for one
  team; ended by closing the round.
- `events` gains `owner_id` (data isolation), `results_published_at`,
  `results_round_id`, and the voting settings (`voting_mode`, `voting_method`,
  `voting_opens_at/closes_at`, `voting_max_votes`, `voting_credits`,
  `voting_round_id`). `events.submissions_close` mirrors the last round's
  deadline.
- `projects` gains `round_id`. **One submission per team per round is enforced
  by the API** (POST replaces; a row lock serialises double-clicks), *not* by a
  unique constraint: `fixtures.json` deliberately contains a duplicate
  (`prj_41` repeats team `tm_07`), and the platform must load fixtures as-is.
  The gallery shows a team's latest round; the duplicate stays visible.
- `project_files`: project_id, original filename, random `stored_name`,
  content_type, size_bytes.

**Voting and community**
- `votes`: event_id, project_id, `voter_key` (salted SHA-256 of account id,
  lower-cased email, or browser token), `voter_kind`, votes, credits_spent,
  `ip_hash`, `voided_at`. One row per (voter, project); a new ballot replaces
  the voter's previous rows.
- `vote_allowlist`: (event_id, pattern): exact emails or `@domain`.
- `comments`: project_id, author_id, body, `hidden_at`.
- `prize_awards`: event_id, prize_id, project_id, rank; written on publish.

**Judging safety and operations**
- `conflict_declarations`: (judge_user_id, project_id, reason). Excluded from
  scoring, progress and "owed reviews".
- `audit_logs`: event_id, actor_label, action, target_type/id, detail,
  ip_hash, created_at. Append-only; the app has no update/delete path.
- `role_invites`: code, role, max_uses, used_count, expires_at, revoked_at,
  label, event_id, created_by.

**Not stored on purpose:** voter emails, browser tokens and IP addresses
(only salted hashes), and any live-update payload (sockets carry topic names
only).

## Platform layer: API keys, webhooks, certificates, audit chain

- `api_keys`: event_id, user_id, name, `prefix`, `key_hash` (SHA-256, unique), scope (`read`/`write`), created/expires/last_used/revoked. The key itself is never stored.
- `webhooks`: event_id, url, `secret` (needed to sign), events (comma list or `*`), active, consecutive_failures, disabled_reason.
- `webhook_deliveries`: the **outbox**. webhook_id, event_type, payload (JSON text), status (`pending`/`success`/`failed`), attempts, response_code, error, duration_ms, next_attempt_at, delivered_at. Written in the same transaction as the action that caused it.
- `certificates`: event_id, user_id, recipient_name, kind (`participation`/`winner`/`judge`), title (prize name for winners), team_name, project_title, rank, `code` (unique), `signature` (HMAC over the contents), issued_at/by, revoked_at. Unique on (event, user, kind, title) so issuing is idempotent.
- `audit_heads`: one row per event (`_global` for event-less entries): the chain's latest `seq` and `last_hash`. Advanced by compare-and-swap.

Related columns on core tables:
- `audit_logs` gained `event_key`, `seq`, `prev_hash`, `row_hash`; unique on (`event_key`, `seq`).
- `events` gained `results_anchor_seq` / `results_anchor_hash` (the chain position when results were published).
- `rounds` gained `closed_notified_at` (so a passed deadline fires `round.closed` once).

## Automation and integrity

- `email_outbox`: one row per email. event_id, user_id, to_email, kind (`welcome`, `submission_receipt`, `deadline_reminder`, `certificate`, …), subject, body_text, body_html, `attachment_ref` (e.g. a certificate, rendered as a PDF at send time and never stored as a blob), `dedupe_key` (unique, so a reminder is never queued twice), status (`pending`/`sent`/`failed`/`skipped`), attempts, error, next_attempt_at, sent_at. Written in the same transaction as the action that caused it.
- `mail_settings`: per event: enabled, reminders_enabled, reminder_hours (e.g. `24,3`), certificate_emails. No row means everything is on.
- `mail_preferences`: per user: reminders, updates. Emails a person needs to act on (invites, receipts, assignments, certificates) ignore these.
- `judge_expertise`: (event_id, judge_user_id, track_id), unique. Used by auto-assignment; seeded from the demo data's judge tracks.
- `repo_scans`: one row per project. repo (`owner/name`), status (`pending`/`done`/`skipped`/`error`), error, commit_sha, is_fork, fork_parent, commit_count, first_commit_at, last_commit_at, file_count, `fingerprints` (code fingerprints per file; never sent to the browser, and no source code is stored), scanned_at.

All five are separate tables, so adding them never alters an existing table.

## Import and export paths

- **CSV import** (Organizer → Data & records): `POST /events/{id}/import` for teams, submissions or judge assignments, with a row-by-row dry run before anything is saved. `GET /events/{id}/import/template` gives the exact columns. Details in `INTEGRATIONS.md`.
- **Export:** `GET /events/{id}/export/projects.csv`, `GET /events/{id}/export/teams.csv`, the score sheet `GET /export.csv?event_id=…`, the audit trail `GET /events/{id}/audit.csv`, and the whole event as JSON with `GET /events/{id}/export/bundle.json` (`format: launchpad-event-bundle/1`). The CSV exports use the importer's columns, so they load straight back in.
