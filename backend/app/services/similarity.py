"""Duplicate and copied-submission detection: deterministic, offline, no AI.

Two projects are related when they share a repository or video link, or
their text overlaps heavily (Jaccard similarity of word triples). The same
team appearing twice is reported as a duplicate ENTRY; different teams as a
POSSIBLE COPY, for a human to judge. Nothing is blocked or auto-penalised.
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

TEXT_THRESHOLD = 0.6
MIN_WORDS = 10          # a description shorter than this isn't enough to compare
MIN_SHINGLES = 6        # ...and after boilerplate is removed, this much distinctive text must remain
COMMON_SHARE = 0.25     # a phrase in more than a quarter of the projects is a template, not copying
COMMON_MIN_COUNT = 4
MAX_PROJECTS = 1500


def norm_url(url: Optional[str]) -> str:
    if not url or not url.strip():
        return ""
    try:
        parts = urlsplit(url.strip().lower())
    except ValueError:
        return ""
    host = parts.netloc.removeprefix("www.")
    path = re.sub(r"(\.git)?/*$", "", parts.path)
    return f"{host}{path}" if host else ""


def _shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < MIN_WORDS:
        return set()
    return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}


@dataclass
class Item:
    id: str
    title: str
    team_id: str
    team_name: str
    round_number: Optional[int]
    repo: str = ""
    video: str = ""
    shingles: set = field(default_factory=set)


def make_item(p, team_name: str, round_number: Optional[int]) -> Item:
    # The title is left out on purpose: two projects that merely share a word
    # in their names are not copies. Only the description and stack count.
    text = " ".join(x for x in (p.summary or "", p.tech_stack or "") if x)
    return Item(p.id, p.title, p.team_id, team_name, round_number, norm_url(p.repo_url), norm_url(p.video_url), _shingles(text))


def prune_boilerplate(items: list[Item]) -> list[Item]:
    """Drop phrases that appear in many of the event's projects (templates
    and placeholder text), so only distinctive wording can signal copying."""
    n = len(items)
    counts: dict[str, int] = {}
    for it in items:
        for sh in it.shingles:
            counts[sh] = counts.get(sh, 0) + 1
    common = {sh for sh, c in counts.items() if c >= COMMON_MIN_COUNT and c / n > COMMON_SHARE}
    for it in items:
        it.shingles = it.shingles - common
        if len(it.shingles) < MIN_SHINGLES:
            it.shingles = set()
    return items


def compare(a: Item, b: Item) -> Optional[dict]:
    reasons: list[str] = []
    score = 0.0
    if a.repo and a.repo == b.repo:
        reasons.append("same repository link"); score = 1.0
    if a.video and a.video == b.video:
        reasons.append("same video link"); score = max(score, 1.0)
    if a.shingles and b.shingles:
        j = len(a.shingles & b.shingles) / len(a.shingles | b.shingles)
        if j >= TEXT_THRESHOLD:
            reasons.append(f"{round(j * 100)}% of the description matches"); score = max(score, j)
    if not reasons:
        return None
    same_team = a.team_id == b.team_id
    if same_team and a.round_number != b.round_number:
        return None  # a team building on its own earlier round is expected, not a duplicate
    return {"kind": "duplicate_entry" if same_team else "possible_copy", "score": round(score, 2), "reasons": reasons}


def find_pairs(items: list[Item]) -> list[dict]:
    items = prune_boilerplate(items[:MAX_PROJECTS])
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            hit = compare(items[i], items[j])
            if hit:
                a, b = items[i], items[j]
                out.append({**hit, "a": {"project_id": a.id, "title": a.title, "team_name": a.team_name, "round": a.round_number},
                            "b": {"project_id": b.id, "title": b.title, "team_name": b.team_name, "round": b.round_number}})
    out.sort(key=lambda x: (-x["score"], x["kind"]))
    return out
