# Judging: Assignment, Scoring, Normalization, and Role Isolation

## 1. Judge assignment

Two ways, both enforced server-side: a judge can only read or score projects
assigned to them. Anything else returns `403`, checked against the
`judge_assignments` table, never left to the frontend.

- **Automatic (recommended).** Organizer → Judging panel → Auto-assign. The
  organizer tags each judge's track expertise and chooses reviews per
  project. The planner then runs repeated optimal matching (the Hungarian
  method, `scipy.optimize.linear_sum_assignment`) to balance workload,
  prefer track experts, and never assign a judge to their own team or a
  declared conflict. The preview is exactly what gets saved. Full method:
  `LAUNCHPAD.md` §2 and `backend/app/services/assignment.py`.
- **Manual.** Assign one judge (by email) to one project with
  `POST /judge/assignments`, for example to fill a gap the planner reports.

Either way, the judge is emailed straight away, and again when scoring opens.

## 2. Scoring rubric

An organizer can configure weighted criteria per event via
`POST /events/{event_id}/criteria` (e.g. `functionality: 1.0`, `quality: 1.5`).
A judge submits scores per criterion (1–5 each) via `POST /judge/scores`,
matching the exact shape `fixtures.json` itself uses:
`{"functionality": 4, "quality": 3, "innovation": 5}`.

If an event has no configured criteria, all submitted criteria are weighted
equally — see `weighted_raw_score()` in
`backend/app/services/normalization.py`.

## 3. Role isolation — where it's enforced, and how it's proven

The single check that matters most for fair judging: **a judge must never
be able to read a peer's scores.**

Enforced in `GET /judge/scores` (`backend/app/api/routes/judging.py`):
a caller may pass `?judge=<email>` to explicitly name whose scores they
want. If that email isn't their own, the request is refused with `403` —
at the API layer, before any data is touched. There is no code path in this
route that returns another judge's scores to someone who isn't them.

This isn't just asserted — it's tested. A real request-level test
(register two judge accounts, have one submit a real score, then have the
other attempt to read it via `?judge=`) returns `403`, verified before this
was ever shipped, and it is re-checked by the end-to-end suite against the
running containers.

**Why email rather than an opaque judge ID as the query parameter:** each
demo/seeded judge's email is stable across restarts (a fresh UUID isn't,
unless explicitly persisted and looked up), and it's human-readable, so
scripts and tests don't have to look up an internal id first.

## 4. Normalization — the method, why, and a worked example

**Method: per-judge z-score (with a floor), then averaged per project.**

For each judge, their scored projects' weighted raw scores are converted
to z-scores: `(value - that judge's own mean) / max(that judge's own
stdev, 1.0)`. That floor of `1.0` isn't cosmetic — it's the result of a
real, measured finding. See **section 8, Normalization Proof**, for the
full investigation: naive z-score (no floor) was measured to make
judges agree with each other *less*, not more, on the real fixture
data, and the floor is what fixes that. A project's final normalized
score is the mean of the z-scores every judge who reviewed it gave it.

**Why z-score over min-max or percentile:** it corrects for both a judge's
average harshness/generosity *and* the spread they use (a judge who only
ever uses a narrow band, e.g. 3–4 out of 5, gets stretched out just as much
as one who uses the full 1–5 range) — min-max normalization alone doesn't
correct for spread, only for range endpoints. Percentile-based ranking is
defensible too, but discards the actual magnitude of disagreement between
judges, which z-score preserves.

**Worked example, using the demo data (`prj_01`):**

| Judge | Score for prj_01 | Judge's own mean | Spread | Normalized |
|---|---|---|---|---|
| jdg_08 | 2.667 | 3.444 | 0.685 | −0.778 |
| jdg_03 | 4.333 | 3.833 | 0.500 | +0.500 |
| jdg_28 | 3.333 | 3.167 | 0.167 | +0.167 |

The raw average is 3.444 (rank 26 of 41). The normalized average is −0.037,
which moves the project up to rank 22: `jdg_03` is a generous judge, so their
4.333 counts for less than it looks. Every judge's spread in the demo data
is under the 1.0 floor, so here the method reduces to subtracting each
judge's own average. `NORMALIZATION.md` has the full walkthrough.

## 5. Handling the demo data's deliberately awkward cases

- **A judge who gave every project they reviewed the identical score:**
  their standard deviation is exactly `0`, which would divide by zero
  under naive z-score. `zscore_normalize()` in `normalization.py` detects
  this explicitly and treats that judge's normalized contribution as
  `0.0` (perfectly average) rather than crashing or producing `NaN`.
- **A judge who scored only one project:** no spread exists to compare
  against, so the same `0.0` treatment applies, for the same reason.
- **The duplicate submission** (`prj_07` and `prj_41`, same team `tm_07`,
  same `repo_url`, different `submitted_at`): both are loaded and scored
  independently, exactly as given in the fixture, so the documented
  normalization numbers stay reproducible. For *new* submissions the rule is
  the opposite: a team has one submission per round and resubmitting replaces
  it, so duplicates cannot arise going forward (see `DATA-MODEL.md`).
  The duplicate detector flags this pair to the organizer (same team, same
  link) without deciding for them. The code check goes further, comparing
  the repositories' actual code (`LAUNCHPAD.md` §4).
- **Projects with anywhere from 0 to 5 reviews:** the results calculation
  only includes projects that have at least one assignment, and
  `judge_count` is reported per project so an organizer can see at a
  glance which projects are under-reviewed before trusting the ranking.

## 6. CSV export

`GET /export.csv?event_id=…` (organizer-only) returns the score rows **for
one event**, and only an event the caller owns. With no `event_id` it exports
the caller's newest event, never "everything"; an organizer with no events
gets an empty file. The event is echoed in an `X-Export-Event` header. Cells
that could be read as spreadsheet formulas are neutralised. Rows include: project id,
project title, judge id, the full criteria breakdown, and the judge's
comment. Verified to return `200` with a genuinely comma-containing body,
not just a `200` with an empty response.

## 7. Input validation on scores

Each criterion score must be between 1 and 5 (matching `fixtures.json`'s
own convention), enforced server-side in `schemas/judging.py`. This
wasn't there from the start — it was added after a real submitted score
showed up in a CSV export with values like `7.6` and `8.0`, silently
accepted because no range check existed yet. Left alone, an out-of-range
score would have quietly distorted that judge's mean/stdev in the
z-score calculation and skewed that project's final ranking without any
visible error. Confirmed fixed with a real request-level test: an
out-of-range submission now returns `422`, a valid one still returns
`201`.

## 8. Bonus challenge: Normalization Proof

**What this proves, and why the first version of it was wrong.**

The naive claim would be: "z-score normalization corrects for judge
disagreement, so judges should agree with each other more after
normalizing." We tested this directly against the real fixture data
rather than assuming it, and the first honest result was **the
opposite of what we expected.**

**Step 1 — reproduce the baseline.** Averaging every criterion score a
judge gave across all their reviews, then measuring the spread (standard
deviation) of those per-judge averages across all 30 judges in
`fixtures.json`:

```
Raw judge spread (σ): 0.4127–0.4198
```

(Two equivalent ways of computing the per-judge mean — flattening every
criterion value together, versus averaging each score entry first and
then averaging those — give the same number, as they mathematically
must when every entry has the same number of criteria.)

**Step 2 — the wrong way to "prove" normalization works.** Z-score
normalization mathematically *forces* every judge's own average to
exactly 0, by definition of the formula. So computing "spread of judges'
means after normalization" trivially returns `0.0` — that's not evidence
the method works, it's just restating what z-score *is*. We caught
this before writing it up as if it meant something.

**Step 3 — the honest test.** The real question is: *for the same
project, do judges' scores end up closer together after normalizing?*
Measuring, per project (across all 41 projects with 2+ reviewers), the
spread of raw scores versus the spread of normalized scores:

```
Average RAW per-project disagreement:        0.4618
Average NORMALIZED per-project disagreement:  0.7046
Change: -52.6%  (WORSE, not better)
```

**Naive z-score made judges agree with each other LESS, not more.**

**Step 4 — why, and the fix.** Z-score divides each score by that
judge's *own* standard deviation. A judge who happens to barely vary
their scores (a small but nonzero spread — e.g. mostly giving 3s and
4s) gets that tiny variation amplified into large swings, since
dividing by a small number inflates whatever difference exists. That
judge's scores then dominate every project they touch, drowning out
judges who use a wider natural range. This is a known, real weakness of
naive z-score, not a flaw in our arithmetic (already hand-verified
correct in section 4's worked cases).

**The fix:** floor how small a judge's divisor is allowed to get. We use
**1.0**, one full point on the 1–5 scale: a principled, explainable value
rather than a tuned one. With the floor in place:

```
Average RAW per-project disagreement:        0.4618
Average NORMALIZED per-project disagreement:  0.395
Change: +14.5% (judges agree MORE)
```

**Why this comparison is fair, and why we don't push the floor higher.**
Every judge in the demo data has a spread under 1.0 (the largest is
0.76), so with the floor at 1.0 every divisor is exactly 1. Normalized
scores are then in the same units as raw scores (points), and the two
numbers compare like-for-like. Raising the floor to 1.25 or 1.5 would make
the number smaller, but only because everything gets divided by a bigger
constant. That shrinks the units without improving agreement, so it would
be a misleading "gain". In practice, then, the floor makes normalization
remove each judge's harsh or generous offset, and spread correction kicks
in only for judges who genuinely use a wide range.

**This entire investigation — the wrong result, catching why it was
wrong, and the real fix — is the actual proof**, reproducible by anyone
against the real `fixtures.json`, not a cherry-picked success story.

## 9. Bonus challenge: Pairwise Mode (Bradley-Terry)

**Why this exists, and why it's optional:** absolute scoring (sections
1–7 above) has a real weakness — a "4" from a harsh judge and a "4" from
a lenient judge don't mean the same thing, which is exactly what
normalization tries to correct for after the fact. Pairwise mode avoids
the problem at the source: instead of asking a judge to invent an
absolute number, it asks the much easier, much more natural question
*"which of these two is better?"* — comparing two things side by side is
something people are reliably more consistent at than rating things on
an abstract 1–5 scale.

**How it works:** a judge assigned to at least 2 projects gets shown a
random pair of them (`GET /judge/pairwise/next`) and picks a winner
(`POST /judge/pairwise`). The same integrity rule as regular scoring
applies — a judge can only compare projects they're actually assigned
to, enforced server-side, not left to the frontend.

**Turning many head-to-head results into one ranking:** this is the
Bradley-Terry model, solved via the standard iterative algorithm
(sometimes called Zermelo's algorithm, after Ernst Zermelo, who first
solved it in 1929 for chess tournaments — the same underlying idea
behind chess/game rating systems). Each project gets a "strength" value
such that the probability of project *i* beating project *j* is
`strength_i / (strength_i + strength_j)`. Sorting by strength gives the
final ranking. Implementation: `backend/app/services/bradley_terry.py`.

**Handling the edge cases, the same philosophy as z-score normalization:**
a project that has never lost would otherwise get pushed toward
infinite strength, one that's never won toward zero, and one with zero
comparisons at all has no strength defined whatsoever under the naive
algorithm. We fix this by giving every real project one "virtual" win
and one virtual loss against a fixed reference opponent (held at
strength 1.0) — verified with a hand-checkable test: a perfect
rock-paper-scissors-style cycle (A beats B, B beats C, C beats A,
equally often) correctly produces near-equal strengths for all three,
since no consistent winner actually exists in that data.

**Verified end-to-end**, not just unit-tested in isolation: a real judge
fetched pairs, submitted comparisons, was correctly blocked from
comparing an unassigned project (`403`), a self-comparison was correctly
rejected (`422`), an invalid winner was correctly rejected (`422`), and
the resulting Bradley-Terry ranking correctly ordered projects by their
actual win record.

**This is an alternative to, not a replacement for, the primary 1-5
scoring system** — both exist side by side (`GET /events/{id}/results`
for the z-score method, `GET /events/{id}/pairwise-results` for this
one), and an organizer or judge can use either.


## 10. When judging may start, and conflicts of interest

**The gate.** A judge can *read* everything a team submitted (text, links,
files) as soon as they are assigned, but can *score* (or compare head-to-head)
only once that round's submissions are closed: the deadline has passed, **or**
the organizer closed submissions early, and no extra time granted to that team
is still running. Otherwise the API answers `409` and the UI shows the project
as LOCKED. This means a team can never change work that is already being
scored. If an organizer reopens a round that already has scores, the scores
are kept and the audit log records how many existed.

**Multi-round.** Results and exports are per round, so Round 1 ideas and
Round 2 builds are ranked separately; "advance top N" advances by the current
normalized ranking.

**Conflicts of interest.**
- A judge who is on a team is *automatically* conflicted on that team's
  project: the organizer cannot assign it (`400`).
- Any assigned judge can declare a conflict, with a reason, **until they have
  scored that project**. After that it is refused (`409`), so a conflict
  cannot be used to retract an unfavourable score.
- A conflicted project cannot be scored or compared, does not count as an
  owed review in progress numbers, and shows up in the organizer's list with
  the reason and a one-click "remove assignment" to reassign. An assignment
  that already has a score cannot be removed.
