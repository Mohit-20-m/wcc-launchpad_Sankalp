"""Auto-balancing judge assignment.

GOAL. Give every project K reviews, spread the work evenly across judges,
prefer judges who know the project's track, and never assign a judge to a
project they are conflicted on.

METHOD. Repeated optimal matching. A single assignment problem can't express
"K different judges per project" (the solver could hand the same judge the
same project twice), so we solve K rounds. In each round every project that
still needs a review gets at most one NEW judge, chosen by
scipy.optimize.linear_sum_assignment (the Hungarian method), which finds
the minimum total cost matching, not a greedy one.

Each judge is expanded into "slots" up to a balanced capacity
(ceil(total reviews / judges)). A slot's cost grows with how loaded the judge
already is, so the solver prefers whoever has the least work. On top of that:

    cost(judge, project) = load_cost + track_cost
    track_cost = 0         judge lists the project's track as expertise
               = GENERALIST judge lists no expertise at all
               = MISMATCH  judge lists other tracks ("strict" mode: forbidden)
    forbidden  = judge is on the project's team, declared a conflict, or
                 already reviews this project

Forbidden pairs get a prohibitive cost and are discarded if the solver had
no other option, so a project the pool cannot cover is reported as short,
never silently given a conflicted judge.

The plan is deterministic (inputs are sorted by id), so a preview and the
commit that follows it produce the same assignments unless the data changed.
"""
from dataclasses import dataclass, field
from math import ceil
from typing import Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

FORBIDDEN = 1e9
LOAD_STEP = 1.0
GENERALIST = 2.0
MISMATCH = 6.0


@dataclass
class JudgeIn:
    id: str
    name: str
    email: str
    tracks: set[str] = field(default_factory=set)
    load: int = 0  # existing assignments in this event


@dataclass
class ProjectIn:
    id: str
    title: str
    team_id: str
    track_id: Optional[str]
    track_name: Optional[str]
    existing_judges: set[str] = field(default_factory=set)


def track_cost(judge: JudgeIn, project: ProjectIn, mode: str) -> float:
    if mode == "ignore" or project.track_id is None:
        return 0.0
    if project.track_id in judge.tracks:
        return 0.0
    if not judge.tracks:
        return GENERALIST if mode != "strict" else FORBIDDEN
    return MISMATCH if mode != "strict" else FORBIDDEN


def plan(
    judges: list[JudgeIn],
    projects: list[ProjectIn],
    blocked: set[tuple[str, str]],
    reviews_per_project: int,
    max_per_judge: Optional[int] = None,
    track_mode: str = "prefer",
) -> dict:
    judges = sorted(judges, key=lambda j: j.id)
    projects = sorted(projects, key=lambda p: p.id)
    k = max(1, reviews_per_project)
    need = {p.id: max(0, k - len(p.existing_judges)) for p in projects}
    total_new = sum(need.values())
    load = {j.id: j.load for j in judges}
    taken: dict[str, set[str]] = {p.id: set(p.existing_judges) for p in projects}
    new_pairs: list[tuple[JudgeIn, ProjectIn, float]] = []

    if not judges or total_new == 0:
        cap = max_per_judge or 0
    else:
        balanced = ceil((sum(load.values()) + total_new) / len(judges))
        cap = min(balanced, max_per_judge) if max_per_judge else balanced

    by_id_p = {p.id: p for p in projects}
    for _ in range(k):
        rows = [p for p in projects if need[p.id] > 0]
        slots: list[tuple[JudgeIn, int]] = []
        for j in judges:
            free = cap - load[j.id]
            for s in range(max(0, free)):
                slots.append((j, load[j.id] + s))
        if not rows or not slots:
            break
        cost = np.full((len(rows), len(slots)), FORBIDDEN)
        for r, p in enumerate(rows):
            for c, (j, level) in enumerate(slots):
                if j.id in taken[p.id] or (j.id, p.id) in blocked:
                    continue
                tc = track_cost(j, p, track_mode)
                if tc >= FORBIDDEN:
                    continue
                cost[r, c] = level * LOAD_STEP + tc
        ri, ci = linear_sum_assignment(cost)
        progressed = False
        for r, c in zip(ri, ci):
            if cost[r, c] >= FORBIDDEN:
                continue
            p, (j, _lvl) = rows[r], slots[c]
            taken[p.id].add(j.id)
            need[p.id] -= 1
            load[j.id] += 1
            new_pairs.append((j, p, track_cost(j, p, track_mode)))
            progressed = True
        if not progressed:
            break

    # Summary for the organizer.
    per_judge = {}
    for j in judges:
        per_judge[j.id] = {"judge_user_id": j.id, "name": j.name, "email": j.email, "tracks": len(j.tracks),
                           "existing": j.load, "new": 0, "total": j.load}
    for j, p, _ in new_pairs:
        per_judge[j.id]["new"] += 1
        per_judge[j.id]["total"] += 1
    matched = sum(1 for _, p, tc in new_pairs if p.track_id is not None and tc == 0.0)
    with_track = sum(1 for _, p, _tc in new_pairs if p.track_id is not None)
    short = [
        {"project_id": pid, "title": by_id_p[pid].title, "missing": n,
         "reason": "Not enough eligible judges (conflicts, team membership, track rules or capacity)."}
        for pid, n in need.items() if n > 0
    ]
    totals = [v["total"] for v in per_judge.values()] or [0]
    return {
        "assignments": [
            {"judge_user_id": j.id, "judge_name": j.name, "judge_email": j.email, "project_id": p.id, "project_title": p.title,
             "track": p.track_name, "track_match": (tc == 0.0 and p.track_id is not None) if track_mode != "ignore" else None}
            for j, p, tc in new_pairs
        ],
        "judges": sorted(per_judge.values(), key=lambda x: (-x["new"], x["name"])),
        "summary": {
            "projects": len(projects),
            "judges": len(judges),
            "reviews_per_project": k,
            "reviews_needed": total_new,
            "reviews_planned": len(new_pairs),
            "capacity_per_judge": cap,
            "track_match_rate": round(matched / with_track, 3) if with_track else None,
            "load_min": min(totals),
            "load_max": max(totals),
            "projects_short": len(short),
        },
        "short": short,
    }
