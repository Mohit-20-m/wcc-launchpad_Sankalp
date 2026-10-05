"""Judge score anomaly detection.

Flags patterns that deserve a human look. Nothing here changes a score,
removes a judge or re-ranks anything: it informs the organizer, who decides.

Every check compares a judge with their CO-JUDGES ON THE SAME PROJECTS
(leave-one-out consensus), never with a global average, so a judge who
simply drew a stronger batch of projects is not flagged as "lenient".

Checks (n = how many projects the judge scored):

  flat            n >= 3 and every overall score identical. The judge isn't
                  separating projects at all.
  no_separation   n >= 3 and in >= 80% of reviews every criterion got the same
                  number (e.g. 4/4/4): criteria aren't being judged separately.
  bias            m >= 3 projects with co-judges, |mean offset| >= 0.75 points
                  and |t| >= 2 (offset is consistent, not noise). Normalization
                  already corrects this in the final ranking; it is shown so
                  the organizer knows.
  outlier         a single review >= 1.5 points away from the average of at
                  least two co-judges on that project.
  reversed        m >= 4 and Spearman correlation with co-judge consensus
                  <= -0.3: the judge ranks projects roughly opposite to peers.
  influence       leave-one-judge-out: recompute the normalized ranking
                  without this judge. If the top 3 changes, the outcome
                  depends heavily on one person.
"""
import statistics
from math import sqrt
from typing import Optional

import numpy as np

from app.services.normalization import aggregate_project_scores, weighted_raw_score, zscore_normalize

SEVERITY = {"flat": 3, "reversed": 3, "influence": 1, "bias": 2, "outlier": 1, "no_separation": 1}


def _rank(values: list[float]) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(len(values))
    # average ties
    vals = np.asarray(values)
    for v in np.unique(vals):
        idx = np.where(vals == v)[0]
        if len(idx) > 1:
            ranks[idx] = ranks[idx].mean()
    return ranks


def spearman(a: list[float], b: list[float]) -> Optional[float]:
    if len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _ranking(by_judge: dict[str, list[tuple[str, float]]]) -> list[str]:
    agg = aggregate_project_scores(zscore_normalize(by_judge))
    return [pid for pid, _ in sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))]


def analyse(scores: list, weights: dict[str, float], judge_info: dict[str, tuple[str, str]], titles: dict[str, str]) -> dict:
    """scores: Score rows (judge_user_id, project_id, criteria)."""
    raw: dict[tuple[str, str], float] = {}
    uniform: dict[str, list[bool]] = {}
    by_judge: dict[str, list[tuple[str, float]]] = {}
    by_project: dict[str, dict[str, float]] = {}
    for s in scores:
        v = weighted_raw_score(s.criteria, weights)
        raw[(s.judge_user_id, s.project_id)] = v
        by_judge.setdefault(s.judge_user_id, []).append((s.project_id, v))
        by_project.setdefault(s.project_id, {})[s.judge_user_id] = v
        vals = list(s.criteria.values())
        uniform.setdefault(s.judge_user_id, []).append(len(vals) > 1 and len(set(vals)) == 1)

    full_rank = _ranking(by_judge) if by_judge else []
    top3 = set(full_rank[:3])
    pos = {pid: i for i, pid in enumerate(full_rank)}

    judges_out = []
    for jid, entries in by_judge.items():
        values = [v for _, v in entries]
        n = len(values)
        flags: list[dict] = []
        sd = statistics.pstdev(values) if n > 1 else 0.0

        if n >= 3 and sd == 0:
            flags.append({"kind": "flat", "message": f"Gave all {n} projects the same overall score ({values[0]:.2f})."})

        u = uniform.get(jid, [])
        if n >= 3 and sum(u) / len(u) >= 0.8:
            flags.append({"kind": "no_separation", "message": f"Gave every criterion the same number in {sum(u)} of {len(u)} reviews."})

        devs, mine, peers, outliers = [], [], [], []
        for pid, v in entries:
            others = [x for j2, x in by_project.get(pid, {}).items() if j2 != jid]
            if not others:
                continue
            consensus = sum(others) / len(others)
            d = v - consensus
            devs.append(d)
            mine.append(v)
            peers.append(consensus)
            if len(others) >= 2 and abs(d) >= 1.5:
                outliers.append({"project_id": pid, "title": titles.get(pid, pid), "score": round(v, 2),
                                 "co_judges": round(consensus, 2), "difference": round(d, 2)})
        m = len(devs)
        mean_dev = sum(devs) / m if m else None
        if m >= 3 and mean_dev is not None and abs(mean_dev) >= 0.75:
            sdd = statistics.stdev(devs) if m > 1 else 0.0
            t = float("inf") if sdd == 0 else mean_dev / (sdd / sqrt(m))
            if abs(t) >= 2:
                word = "harsher" if mean_dev < 0 else "more lenient"
                flags.append({"kind": "bias", "message": f"Consistently {word} than co-judges on the same projects, by {abs(mean_dev):.2f} points on average across {m} projects. Normalization already corrects for this."})
        for o in outliers:
            direction = "below" if o["difference"] < 0 else "above"
            flags.append({"kind": "outlier", "message": f"Scored \u201c{o['title']}\u201d {abs(o['difference']):.2f} points {direction} the other judges ({o['score']} vs {o['co_judges']}).", "project_id": o["project_id"]})
        rho = spearman(mine, peers) if m >= 4 else None
        if rho is not None and rho <= -0.3:
            flags.append({"kind": "reversed", "message": f"Ranks projects largely opposite to co-judges (rank correlation {rho:.2f} over {m} projects)."})

        # Leave-one-judge-out influence on the final ranking.
        influence = None
        if len(by_judge) > 1 and full_rank:
            without = {k: v for k, v in by_judge.items() if k != jid}
            alt = _ranking(without)
            alt_pos = {pid: i for i, pid in enumerate(alt)}
            moves = [abs(pos[pid] - alt_pos[pid]) for pid, _ in entries if pid in alt_pos]
            changed_top3 = set(alt[:3]) != top3 and len(full_rank) >= 3
            influence = {"max_rank_shift": max(moves) if moves else 0, "changes_top3": changed_top3}
            if changed_top3:
                flags.append({"kind": "influence", "message": "Removing this judge's scores would change who finishes in the top 3."})

        severity = sum(SEVERITY[f["kind"]] for f in flags)
        name, email = judge_info.get(jid, ("", ""))
        judges_out.append({
            "judge_user_id": jid, "name": name, "email": email, "reviews": n,
            "mean": round(sum(values) / n, 2), "spread": round(sd, 2),
            "mean_offset": round(mean_dev, 2) if mean_dev is not None else None,
            "agreement": round(rho, 2) if rho is not None else None,
            "influence": influence, "severity": severity, "flags": flags,
        })

    judges_out.sort(key=lambda j: (-j["severity"], j["name"]))
    flagged = [j for j in judges_out if j["flags"]]
    return {
        "judges": judges_out,
        "summary": {
            "judges_analysed": len(judges_out),
            "judges_flagged": len(flagged),
            "reviews": len(raw),
            "by_kind": {k: sum(1 for j in judges_out for f in j["flags"] if f["kind"] == k) for k in SEVERITY},
            # How fragile the podium is: how many single judges could change it.
            "top3_depends_on_judges": sum(1 for j in judges_out if j["influence"] and j["influence"]["changes_top3"]),
        },
        "note": "Flags are prompts for a human conversation, not verdicts. Nothing is changed automatically.",
    }
