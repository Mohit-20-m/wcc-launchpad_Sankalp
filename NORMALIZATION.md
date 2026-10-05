# Score normalization

Judges score on different internal scales: one judge's "3" is another's
"4". Averaging raw scores rewards whichever teams happened to draw the
generous judges. WCC Launchpad corrects for this before ranking.

## The method

For each judge, every overall score they gave is re-expressed relative to
**that judge's own scoring**:

```
normalized = (score - judge's own mean) / max(judge's own spread, 1.0)
```

A project's normalized score is the average of the normalized scores from
all its judges, and projects are ranked by it. The code is in
`backend/app/services/normalization.py`.

- **"Score"** is the judge's weighted overall score for the project, using
  the organizer's rubric weights.
- **"Spread"** is the standard deviation of everything that judge scored.
- **The floor of 1.0** (one point on the 1–5 scale) stops a judge who barely
  varies, for example giving only 3s and 4s, from having tiny differences
  blown up into huge swings.
- **Edge cases:** a judge who scored only one project, or gave every project
  the same score, contributes 0, which means "exactly average for this
  judge". This keeps the maths free of division by zero and of
  not-a-number results.

### Why this and not min-max or percentiles

| Method | Corrects harsh/generous judges | Keeps how much better a project is | Problem |
|---|---|---|---|
| Raw average | no | yes | rewards lucky judge draws |
| Min-max per judge | partly | yes | one extreme score distorts the whole scale |
| Percentile per judge | yes | **no** | "slightly better" and "far better" look the same |
| **Centered and scaled (ours)** | **yes** | **yes** | needs a floor for low-spread judges (we have one) |

## What it does on the demo data, honestly

In the demo data (30 judges, 126 scores, 41 projects), **every judge's
spread is below 1.0**: the largest is 0.76. So the floor applies to every
judge, and on this data the method reduces to **subtracting each judge's
own average**. That is the part that matters most here: it removes harsh
and generous offsets.

Spread correction takes effect only for a judge whose spread exceeds one
point, meaning someone using the full 1–5 range. That's exactly when it
should apply.

## Worked example: `prj_01`

Three judges scored `prj_01`. Each score is compared with the average of
everything **that judge** scored:

| Judge | Projects scored | Score for prj_01 | Judge's own mean | Spread | Divisor (floor 1.0) | Normalized |
|---|---|---|---|---|---|---|
| jdg_08 | 3 | 2.667 | 3.444 | 0.685 | 1.0 | **−0.778** |
| jdg_03 | 2 | 4.333 | 3.833 | 0.500 | 1.0 | **+0.500** |
| jdg_28 | 2 | 3.333 | 3.167 | 0.167 | 1.0 | **+0.167** |

- **Raw average:** (2.667 + 4.333 + 3.333) / 3 = **3.444**, rank **26** of 41.
- **Normalized:** (−0.778 + 0.500 + 0.167) / 3 = **−0.037**, rank **22** of 41.

`jdg_03`'s 4.333 looks high in raw terms, but `jdg_03` is a generous judge
(own mean 3.833), so it counts as only half a point above their norm.
`jdg_08`'s 2.667 is well below that judge's own average, so it pulls harder.
The project moves up four places once each judge's habits are accounted for.

Across all 41 projects, the biggest shifts are `prj_07` (up 16 places) and
`prj_19` (down 14). These are projects whose raw position mostly reflected
which judges they drew. The top five change from
`prj_11, prj_34, prj_10, prj_25, prj_37` (raw) to
`prj_34, prj_37, prj_33, prj_11, prj_25` (normalized).

## Does it make judges agree more?

We measured whether, for the same project, judges' scores end up closer
together after normalizing. This is the per-project spread, averaged over
every project with two or more reviews:

| | Average per-project disagreement |
|---|---|
| Raw scores | 0.4618 |
| Normalized (floor 1.0) | **0.395**, i.e. 14.5% less disagreement |

With the floor at 1.0 the divisor is exactly 1 for every judge here, so both
rows are in the same units (points on the 1–5 scale). The comparison is
like-for-like.

We also tested a *naive* version with no floor. It made disagreement
**worse** (0.7046): dividing by a judge's tiny spread exaggerated noise from
judges who barely vary. That finding is why the floor exists. Floors above
1.0 would make the number look smaller, but only because everything is
divided by a bigger constant. That shrinks the units without improving
agreement, so we don't claim it as a gain. The full investigation is in
`JUDGING.md` (section 8).

## Where to see it

- **Organizer → Results:** the normalized ranking, shown next to the
  Bradley–Terry ranking from head-to-head comparisons.
- **`GET /events/{id}/results`:** the same numbers through the API.
- **Organizer → Results → Scoring health check:** flags the judge
  behaviours normalization can't fix, such as a judge who gives everyone the
  same score, ranks projects opposite to their peers, or could single-handedly
  change the top three. See `LAUNCHPAD.md`.
