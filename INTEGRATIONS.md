# Integrations and platform layer

API keys, outbound webhooks, certificates and bulk import/export, plus two
additions that fit the platform's theme of *provable fairness*: a
tamper-evident audit trail and duplicate-submission detection.

Everything here works offline. Nothing calls out except webhooks you configure.
(Email and the GitHub code check are separate, optional features: see `LAUNCHPAD.md`.)

Interactive API docs: **/api/docs**. Every UI action below is one of these calls.

---

## 1. API keys

Organizer console → **Integrations** → *API keys*.

```bash
curl -H "Authorization: Bearer dgf_XXXX…" http://localhost:8080/api/events/EVENT_ID/stats
```

- A key belongs to **one event** and is **read** (GET only) or **write**.
- It acts as the organizer who made it, for that event only. It cannot touch
  another event (even one the same organizer owns), create events, mint
  invites, list all events, or create more keys.
- Only a SHA-256 of the key is stored. The key is shown **once**, at creation.
- Optional expiry; revoke any time (takes effect on the next request).
- `last used` is tracked (updated at most once a minute).

## 2. Webhooks

Organizer console → **Integrations** → *Webhooks*. Up to 10 per event. Each
endpoint chooses which event types it wants (or everything).

### Event types

| Type | Fires when |
|---|---|
| `team.created`, `team.joined` | a team is created / someone joins |
| `submission.created`, `submission.replaced`, `submission.updated` | a build is submitted, resubmitted (replaces the old one), or edited |
| `submission.flagged_similar` | a submission resembles another (see §6) |
| `round.closed` | the organizer closes a round early **or its deadline passes** (exactly once) |
| `round.extended`, `round.advanced` | a round is extended / teams advance |
| `results.published`, `results.unpublished` | results go public / are withdrawn |
| `certificate.issued` | certificates were issued (counts in `data.detail`) |
| `import.completed` | a bulk import was committed |
| `webhook.test` | you pressed *Send test* |

The list is also public at `GET /api/webhook-event-types`.

### Request

`POST` your URL with `Content-Type: application/json`:

```json
{
  "id": "0b5f…",                // unique per event; retries reuse it, so de-duplicate on it
  "type": "submission.created",
  "created_at": "2026-09-28T12:00:00+00:00",
  "event_id": "…",
  "data": { "action": "submission.create", "target_type": "project", "target_id": "…", "detail": { "team": "Alpha", "round": 1 } }
}
```

Payloads carry ids and names only. **No emails, tokens or secrets.**

Headers: `X-Launchpad-Event`, `X-Launchpad-Delivery` (unique per delivery),
`X-Launchpad-Signature: t=<unix seconds>,v1=<hex>`.

### Verify the signature

`v1 = HMAC-SHA256(secret, "<t>.<raw body>")`. Use the **raw** bytes, compare in
constant time, and reject a `t` more than a few minutes old (replay protection).

```python
import hmac, hashlib, time

def verify(secret: str, header: str, raw_body: bytes, tolerance=300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    t, sig = parts["t"], parts["v1"]
    if abs(time.time() - int(t)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
```

```js
const crypto = require("node:crypto");
function verify(secret, header, rawBody, tolerance = 300) {
  const p = Object.fromEntries(header.split(",").map((x) => x.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(p.t)) > tolerance) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${p.t}.${rawBody}`).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(p.v1));
}
```

### Delivery guarantees

- **Never lost, never phantom.** Events are written to an outbox table in the
  *same database transaction* as the action. If the action fails, nothing is
  queued; if the server restarts, queued events still go out.
- **At least once.** Any non-2xx (or timeout, 5 s) is retried after
  5 s, 30 s, 2 min, 10 min, 1 h (6 attempts in all). Use `id` to de-duplicate.
  Order is not guaranteed across retries.
- **Delivery log** per endpoint (status, attempts, HTTP code, error, time)
  with a manual **Retry**.
- **Auto-pause.** After 10 deliveries in a row exhaust their retries the
  endpoint is disabled, with the reason shown. Re-enabling resets the count.
- **Secrets:** shown once at creation and on *Rotate secret*.
- **Several backend workers** are safe: each delivery is claimed with an atomic
  update, so it is sent once per attempt.

### URL safety (SSRF)

A webhook must not be usable to probe the platform's own network. URLs are
refused if the scheme isn't http(s), they contain credentials, the host does
not resolve, or **any** resolved address is private, loopback, link-local
(including cloud metadata `169.254.169.254`), multicast or reserved. The check
runs when you save **and again before every send** (DNS can change), and
redirects are not followed.

To test against a receiver on your own machine, set
`WEBHOOK_ALLOW_PRIVATE=true` in `.env` and rebuild. Leave it `false` otherwise.

## 3. Certificates

Organizer console → **Certificates**.

| Kind | Who gets one |
|---|---|
| Participation | every member of a team that submitted a project |
| Winner | members of teams that won a prize (**results must be published first**); includes prize and rank |
| Judge | judges who scored at least one project |

- **Idempotent.** Issue as often as you like; nobody gets two.
- Each has a code like `K7QM-2XVD-9FHT` (no look-alike characters, ~60 bits).
- Recipients see theirs under **Results** (participants) or **My assignments**
  (judges): download the PDF or copy a verification link.
- **Public verification:** `/verify/<code>` (or `GET /api/certificates/verify/<code>`)
  shows who, what and whether it is valid, revoked or not genuine. No sign-in,
  no email address exposed. Lookups are rate-limited per address.
- **Tamper-evident.** Each certificate carries an HMAC over its contents (name,
  kind, prize, rank, date, code). Editing any of them in the database makes
  verification say *not genuine* and withholds the PDF.
- **Revoke** any certificate; its page then says REVOKED. Re-issuing does not
  bring it back.
- The PDF is generated on demand, with a QR code pointing at its verify page.

> Operational note: the signing key is derived from `JWT_SECRET`. **Changing
> `JWT_SECRET` invalidates every certificate already issued.** Set it once.

## 4. Bulk import and export

Organizer console → **Data & records**.

### Import (CSV, UTF-8, ≤ 2 MB, ≤ 5,000 rows)

Download the template for each kind from the same panel.

| Kind | Columns | Notes |
|---|---|---|
| `teams` | `team_name, member_email, member_name` | One row per member; first listed leads. Team size ≤ 4, one team per person per event. Optional **create accounts** makes participant accounts with one-time passwords. |
| `projects` | `team_name, title, summary, tech_stack, repo_url, video_url, track, round` | Team must exist. `round` defaults to 1. Re-importing a team/round **replaces** its submission (same record), never duplicates. |
| `assignments` | `judge_email, project_title, team_name` | Judge must be a judge account. Conflicts of interest (judge on that team) are rejected. Already-assigned pairs are skipped. |

**Check before commit.** *Check file* is a dry run that reports **every row**
(OK / SKIP / ERROR, with the line number and a specific reason) and writes
nothing. A real import with any error is **refused outright** (all or nothing)
unless you choose *import only the valid rows*. Organizer imports bypass round
deadlines (it is your event), but every field is still validated. Imports are
recorded in the audit trail and fire `import.completed`.

Created accounts' one-time passwords are returned **once** in the response and
offered as a CSV download; they are never stored in readable form or shown again.

### Export

`GET /api/events/{id}/export/teams.csv`, `projects.csv`, `bundle.json`. The two
CSVs use **the same columns the importer reads**, so an export can be re-imported.
Cells that could run as spreadsheet formulas are neutralised on export and
restored on import. `bundle.json` is the whole event: rounds, tracks, prizes,
criteria, teams (with members), projects, files, prize awards and the audit
anchor. Exports are organizer-only and event-scoped.

## 5. Tamper-evident audit trail *(added feature)*

Every audit entry stores the hash of the entry before it:
`row_hash = SHA-256(prev_hash ‖ id ‖ time ‖ actor ‖ action ‖ target ‖ detail ‖ ip-hash)`.
Change any past entry, or delete one, and every later hash stops matching.

- **Verify:** Audit trail tab → *Verify integrity* (`GET /events/{id}/audit/verify`).
  It reports the first bad entry by number and whether entries were removed
  from the middle or the end.
- **Concurrency-safe:** the chain head advances with an atomic compare-and-swap,
  so simultaneous requests (or several workers) can never fork the chain.
  Tested with 25 simultaneous requests on SQLite and PostgreSQL.
- **Public anchor:** when results are published, the chain position and hash
  at that moment are recorded and shown on the public results page.
  `GET /api/events/{id}/audit/anchor` (no sign-in) re-checks the log up to that
  point and says whether it still matches, **revealing none of its content.**

**What this proves, and what it does not.** It makes silent edits *detectable*;
it does not make them *impossible*. Someone with write access to the database
could recompute the whole chain from the point they changed. The public anchor
narrows that gap **only if the anchor hash was copied somewhere the organizer
does not control** (a screenshot, a post, the event's pitch deck). Record it
when you publish.

## 6. Duplicate and copied-submission detection *(added feature)*

Submissions tab → *Possible duplicates*. Deterministic, offline, no AI.

Two projects are related when they share a **repository or video link**
(normalized: `www.`, `.git`, trailing slash and case don't matter) or when
their descriptions overlap heavily (Jaccard similarity of word triples ≥ 60%).

- The **same team** appearing twice → *duplicate entry*. Different teams →
  *possible copy*. A team building on its own earlier round is **not** flagged.
- **Boilerplate is ignored.** Phrases that appear in a large share of the
  event's projects (placeholder text, templates) are dropped before comparing,
  and titles are excluded, so two projects that merely share a word or a
  template are not accused. Against the 41-project demo data this flags
  exactly the one deliberate duplicate and nothing else.
- It **never blocks or penalises** anything. It is a prompt for a human.
  Flags are also written to the audit trail at submit time (and can fire
  `submission.flagged_similar`).

---

## Endpoint reference

| Method and path | Who | Purpose |
|---|---|---|
| `POST/GET /events/{id}/api-keys`, `DELETE …/{key}` | organizer (login, not a key) | manage keys |
| `POST/GET /events/{id}/webhooks`, `PATCH/DELETE …/{hook}` | organizer | manage endpoints |
| `POST …/webhooks/{hook}/test`, `/rotate-secret` | organizer | test / rotate |
| `GET …/webhooks/{hook}/deliveries`, `POST …/deliveries/{d}/retry` | organizer | delivery log |
| `GET /webhook-event-types` | public | event catalogue |
| `POST /events/{id}/certificates/issue`, `GET …/certificates`, `POST …/{id}/revoke` | organizer | issue, list, revoke |
| `GET /certificates/mine` | signed in | my certificates |
| `GET /certificates/verify/{code}`, `GET /certificates/{code}/pdf` | public | verify / download |
| `GET /events/{id}/import/template?kind=`, `POST /events/{id}/import` | organizer | template / import (`dry_run`, `create_accounts`, `skip_errors`) |
| `GET /events/{id}/export/{teams.csv,projects.csv,bundle.json}` | organizer | export |
| `GET /events/{id}/audit/verify` | organizer | verify the chain |
| `GET /events/{id}/audit/anchor` | public | publish-time anchor check |
| `GET /events/{id}/similarity` | organizer | duplicate / copy candidates |
