"""Code-level duplicate detection and repository timeline checks.

Deterministic and explainable, no AI. For each submitted GitHub repository:

1. FETCH (GitHub REST API + raw file host): default branch, latest commit,
   fork status, commit count, first/last commit dates, and up to MAX_FILES
   source files (vendored, generated and lock files skipped).

2. NORMALIZE each file into a token stream that survives cosmetic edits:
   comments and whitespace removed, every identifier becomes V, every string
   S, every number N; language keywords and operators are kept. Renaming
   variables or reformatting therefore changes nothing.

3. FINGERPRINT with winnowing (Schleimer, Wilkerson & Aiken, SIGMOD 2003 --
   the algorithm behind Stanford's MOSS): hash every K-token window, keep the
   minimum hash in each sliding window of W hashes. Any shared run of at
   least W+K-1 tokens is guaranteed to produce a shared fingerprint.

4. COMPARE every pair of repositories from different teams. Fingerprints
   found in many repositories (framework scaffolding, starter templates) are
   dropped first, exactly as the text detector drops boilerplate phrases.
   Similarity is reported as Jaccard and containment (the share of the smaller
   repo found in the larger), with the best-matching file pairs as evidence.

Timeline checks use the event's own dates: a first commit well before the
event started, or a repository that is a fork, is shown to the organizer.
Everything is a FLAG for a human; nothing blocks or penalizes a team.
"""
import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.core.config import settings

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

K = 12                 # tokens per k-gram
W = 8                  # winnowing window
MAX_FILES = 80
MAX_FILE_BYTES = 150_000
MAX_TOTAL_BYTES = 3_000_000
MIN_FILE_TOKENS = 40   # tiny files (configs, re-exports) carry no signal
COMMON_SHARE = 0.25
COMMON_MIN = 3
FLAG_JACCARD = 0.25
FLAG_CONTAINMENT = 0.45
MIN_SHARED = 40

SOURCE_EXT = {
    "py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "vue", "svelte", "java", "kt", "kts", "go", "rs", "c", "h", "cc", "cpp",
    "hpp", "cs", "rb", "php", "swift", "dart", "scala", "lua", "r", "m", "sql", "sh", "ex", "exs", "sol",
}
SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt", "target", "venv", ".venv", "env", "__pycache__",
    "coverage", "third_party", "third-party", "bower_components", ".git", "public", "static", "assets", "migrations",
    "site-packages", ".dart_tool", "Pods", "gradle",
}
SKIP_SUFFIX = (".min.js", ".min.css", ".d.ts", ".bundle.js", ".map", "-lock.json", ".lock", ".pb.go", "_pb2.py", ".g.dart")

KEYWORDS = set("""
abstract and as assert async await break case catch class const continue def default defer del delete do elif else enum
except export extends false final finally fn for foreach from func function go goto if impl implements import in instanceof
interface is lambda let loop match mod module mut namespace new nil none not null of or package pass private protected pub
public raise return self static struct super switch this throw throws trait true try type typeof union unsafe use using
val var void where while with yield end then begin elsif unless until require include extern inline override virtual
""".split())

_COMMENT_RE = re.compile(r'/\*.*?\*/|//[^\n]*|"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|<!--[\s\S]*?-->', re.S)
_HASH_COMMENT_RE = re.compile(r"(?m)^\s*#(?!include|define|if|endif|pragma|!).*$|(?<=\s)#\s.*$")
_TOKEN_RE = re.compile(
    r'[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`'
    r'|===|!==|==|!=|<=|>=|&&|\|\||=>|->|::|\+\+|--|\+=|-=|\*=|/=|[{}()\[\];,.:=+\-*/%<>!&|^~?@]'
)
_GH_RE = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9][\w.-]*)/([\w.-]+?)(?:\.git)?(?:/.*)?$")


def parse_github(url: Optional[str]) -> Optional[tuple[str, str]]:
    if not url:
        return None
    m = _GH_RE.match(url.strip())
    if not m:
        return None
    owner, name = m.group(1), m.group(2)
    if name.lower() in {"", "settings", "orgs"}:
        return None
    return owner, name


def tokens(source: str, ext: str) -> list[str]:
    src = _COMMENT_RE.sub(" ", source)
    if ext in {"py", "rb", "sh", "r", "ex", "exs"}:
        src = _HASH_COMMENT_RE.sub(" ", src)
    out = []
    for t in _TOKEN_RE.findall(src):
        c = t[0]
        if c.isalpha() or c in "_$":
            out.append(t if t.lower() in KEYWORDS else "V")
        elif c.isdigit():
            out.append("N")
        elif c in "\"'`":
            out.append("S")
        else:
            out.append(t)
    return out


def _h(s: str) -> int:
    # 52-bit so the numbers also survive a trip through JSON / JavaScript.
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=7).digest(), "big") >> 4


def winnow(toks: list[str], k: int = K, w: int = W) -> list[int]:
    if len(toks) < k:
        return []
    grams = [_h(" ".join(toks[i:i + k])) for i in range(len(toks) - k + 1)]
    if len(grams) <= w:
        return [min(grams)]
    picked: set[int] = set()
    last = -1
    for i in range(len(grams) - w + 1):
        window = grams[i:i + w]
        m = min(window)
        # rightmost minimum, as in the paper, so runs of equal hashes pick once
        j = i + (w - 1 - window[::-1].index(m))
        if j != last:
            picked.add(m)
            last = j
    return sorted(picked)


def fingerprint_files(files: dict[str, str]) -> dict[str, list[int]]:
    out = {}
    for path, text in files.items():
        ext = path.rsplit(".", 1)[-1].lower()
        toks = tokens(text, ext)
        if len(toks) < MIN_FILE_TOKENS:
            continue
        fp = winnow(toks)
        if fp:
            out[path] = fp
    return out


def _wanted(path: str, size: int) -> bool:
    parts = path.split("/")
    if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
        return False
    name = parts[-1].lower()
    if name.endswith(SKIP_SUFFIX) or "." not in name:
        return False
    return name.rsplit(".", 1)[-1] in SOURCE_EXT and 0 < size <= MAX_FILE_BYTES


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "Launchpad-Integrity/1.0", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class ScanError(Exception):
    pass


async def _get(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    r = await client.get(url, headers=_headers(), **kw)
    if r.status_code == 404:
        raise ScanError("Repository not found or private.")
    if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
        reset = r.headers.get("x-ratelimit-reset")
        when = datetime.fromtimestamp(int(reset), timezone.utc).strftime("%H:%M UTC") if reset else "later"
        raise ScanError(f"GitHub rate limit reached; try again after {when} or set GITHUB_TOKEN.")
    if r.status_code >= 400:
        raise ScanError(f"GitHub answered HTTP {r.status_code}.")
    return r


async def fetch_repo(owner: str, name: str) -> dict:
    """Everything we need about one repository, or ScanError."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        meta = (await _get(client, f"{API}/repos/{owner}/{name}")).json()
        full = meta.get("full_name") or f"{owner}/{name}"
        branch = meta.get("default_branch") or "main"
        info = {
            "repo": full, "is_fork": bool(meta.get("fork")),
            "fork_parent": (meta.get("parent") or {}).get("full_name"),
            "created_at": _iso(meta.get("created_at")),
        }
        # Latest commit + total count (from the pagination "last" link) + first commit.
        r = await _get(client, f"{API}/repos/{full}/commits", params={"sha": branch, "per_page": 1})
        latest = r.json()
        if not latest:
            raise ScanError("Repository has no commits.")
        sha = latest[0]["sha"]
        info["commit_sha"] = sha
        info["last_commit_at"] = _iso(latest[0]["commit"]["committer"]["date"])
        count, first_at = 1, info["last_commit_at"]
        last_link = re.search(r'<([^>]+)>;\s*rel="last"', r.headers.get("link", ""))
        if last_link:
            m = re.search(r"[?&]page=(\d+)", last_link.group(1))
            count = int(m.group(1)) if m else 1
            oldest = (await _get(client, last_link.group(1))).json()
            if oldest:
                first_at = _iso(oldest[-1]["commit"]["committer"]["date"])
        info["commit_count"], info["first_commit_at"] = count, first_at

        tree = (await _get(client, f"{API}/repos/{full}/git/trees/{sha}", params={"recursive": "1"})).json()
        blobs = [t for t in tree.get("tree", []) if t.get("type") == "blob" and _wanted(t.get("path", ""), t.get("size", 0))]
        blobs.sort(key=lambda t: -t.get("size", 0))
        chosen, total = [], 0
        for b in blobs:
            if len(chosen) >= MAX_FILES or total + b["size"] > MAX_TOTAL_BYTES:
                continue
            chosen.append(b["path"])
            total += b["size"]

        sem = asyncio.Semaphore(8)
        files: dict[str, str] = {}

        async def grab(path: str) -> None:
            async with sem:
                try:
                    rr = await client.get(f"{RAW}/{full}/{sha}/{path}", headers={"User-Agent": "Launchpad-Integrity/1.0"})
                    if rr.status_code == 200 and len(rr.content) <= MAX_FILE_BYTES:
                        files[path] = rr.content.decode("utf-8", errors="ignore")
                except httpx.HTTPError:
                    pass

        await asyncio.gather(*(grab(p) for p in chosen))
        info["fingerprints"] = fingerprint_files(files)
        info["file_count"] = len(info["fingerprints"])
        return info


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

def compare_all(repos: list[dict]) -> list[dict]:
    """repos: [{project_id, title, team_id, team_name, round, repo, fingerprints}]"""
    n = len(repos)
    if n < 2:
        return []
    union = []
    for r in repos:
        s = set()
        for fp in (r["fingerprints"] or {}).values():
            s.update(fp)
        union.append(s)
    counts: dict[int, int] = {}
    for s in union:
        for x in s:
            counts[x] = counts.get(x, 0) + 1
    common = {x for x, c in counts.items() if c >= COMMON_MIN and c / n > COMMON_SHARE}
    clean = [s - common for s in union]

    out = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = repos[i], repos[j]
            if a["repo"] and b["repo"] and a["repo"].lower() == b["repo"].lower():
                continue  # same link: already reported by the text/link detector
            if a["team_id"] == b["team_id"] and a["round"] != b["round"]:
                continue  # a team building on its own earlier round
            A, B = clean[i], clean[j]
            if not A or not B:
                continue
            shared = A & B
            if len(shared) < MIN_SHARED:
                continue
            jac = len(shared) / len(A | B)
            con = len(shared) / min(len(A), len(B))
            if jac < FLAG_JACCARD and con < FLAG_CONTAINMENT:
                continue
            files = []
            for pa, fa in (a["fingerprints"] or {}).items():
                sa = set(fa) - common
                if len(sa) < 10:
                    continue
                best, best_path = 0.0, None
                for pb, fb in (b["fingerprints"] or {}).items():
                    sb = set(fb) - common
                    if len(sb) < 10:
                        continue
                    c = len(sa & sb) / min(len(sa), len(sb))
                    if c > best:
                        best, best_path = c, pb
                if best >= 0.5 and best_path:
                    files.append({"a": pa, "b": best_path, "overlap": round(best, 2)})
            files.sort(key=lambda f: -f["overlap"])
            out.append({
                "kind": "duplicate_entry" if a["team_id"] == b["team_id"] else "possible_copy",
                "jaccard": round(jac, 2), "containment": round(con, 2), "shared_fingerprints": len(shared),
                "a": {k: a[k] for k in ("project_id", "title", "team_name", "repo")},
                "b": {k: b[k] for k in ("project_id", "title", "team_name", "repo")},
                "files": files[:8],
            })
    out.sort(key=lambda p: (-p["containment"], -p["jaccard"]))
    return out


def timeline_flags(scan, event_start: Optional[datetime], deadline: Optional[datetime], forks_of: dict[str, str]) -> list[dict]:
    flags = []

    def aware(d):
        return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)

    first, last = aware(scan.first_commit_at), aware(scan.last_commit_at)
    start, end = aware(event_start), aware(deadline)
    if start and first and first < start - timedelta(hours=1):
        days = (start - first).days
        flags.append({"kind": "pre_event_commits", "severity": "high" if days >= 2 else "medium",
                      "message": f"First commit is {first:%d %b %Y %H:%M} UTC, before the event started ({start:%d %b %H:%M} UTC). Check the rules on prior work and whether it was disclosed."})
    if end and last and last > end + timedelta(minutes=10):
        flags.append({"kind": "post_deadline_commits", "severity": "info",
                      "message": f"Latest commit is {last:%d %b %Y %H:%M} UTC, after the deadline ({end:%d %b %H:%M} UTC). Judge the commit from before the deadline."})
    if scan.is_fork:
        parent = scan.fork_parent or "another repository"
        inside = forks_of.get((scan.fork_parent or "").lower())
        flags.append({"kind": "fork", "severity": "high" if inside else "medium",
                      "message": f"Repository is a fork of {parent}" + (f", which is another team's submission ({inside})." if inside else ".")})
    if scan.commit_count is not None and scan.commit_count <= 2:
        flags.append({"kind": "few_commits", "severity": "info",
                      "message": f"Only {scan.commit_count} commit(s): the history can't show how the work was built."})
    return flags
