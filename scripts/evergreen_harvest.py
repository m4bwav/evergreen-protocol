"""Harvest targets: the community places a technique harvest checks for each unit (PROTOCOL.md section 8).

A unit may carry an optional `harvest.json` beside its `evergreen.json`, listing the subreddits, forums, feeds
and pages where practitioners post techniques, tools and workflows that could improve it. A technique harvest
(a periodic sweep that tests the best posts and folds winners into the units) reads the merged list instead of
keeping its own, so the list grows with the units and each unit owns its sources.

    harvest targets [roots...] [--unit U] [--json]   merged, deduplicated list with the units each target feeds
    harvest lint <unit>                              check one unit's harvest.json (exit 1 on a problem)
    harvest add <unit> --kind K (--sub S | --url U | --query Q) [--weight W] [--keep TEXT] [--id ID]
    harvest top [--unit U] [-n 10] [--json] [--no-save]  each github query target's top repos by stars; entrants
                                                     new since the last run are marked NEW (EVERGREEN_HOME state)

Stdlib only. The file holds public URLs and filter notes, nothing private, so it may live in a public repository.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import evergreen as eg

FILE = "harvest.json"
KINDS = {"reddit", "rss", "web", "api", "hn", "github"}
WEIGHTS = ["low", "normal", "core"]  # ascending; a merged target takes the highest weight any unit gives it


def target_url(t: dict) -> str:
    """The URL a harvest fetches for a target (a subreddit's top-of-month feed, a query, or the url as given)."""
    k = t.get("kind")
    if k == "reddit":
        return f"https://www.reddit.com/r/{t['sub']}/top/.rss?t=month&limit=100"
    if k == "hn":
        return "https://hn.algolia.com/api/v1/search?tags=story&query=" + quote(t["query"])
    if is_gh_query(t):
        return GH_SEARCH + quote(gh_query(t["query"]))
    return t.get("url", "")


GH_SEARCH = "https://api.github.com/search/repositories?sort=stars&order=desc&per_page=10&q="


def is_gh_query(t: dict) -> bool:
    return t.get("kind") == "github" and bool(t.get("query")) and not t.get("url")


def gh_query(q: str) -> str:
    """The search API takes the sort as a parameter, so a 'sort:stars' qualifier in the query is dropped."""
    return re.sub(r"\s*\bsort:\S+", "", q).strip()


def target_id(t: dict) -> str:
    if t.get("id"):
        return t["id"]
    k = t.get("kind")
    if k == "reddit":
        return f"reddit/{t.get('sub', '').lower()}"
    if k == "hn":
        return "hn/" + re.sub(r"[^a-z0-9]+", "-", t.get("query", "").lower()).strip("-")
    if is_gh_query(t):
        return "github-top/" + re.sub(r"[^a-z0-9]+", "-", gh_query(t["query"]).lower()).strip("-")
    u = re.sub(r"^https?://(www\.)?", "", t.get("url", "")).rstrip("/")
    return f"{k}/{u}"


def load(d: Path) -> dict | None:
    p = Path(d) / FILE
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def problems(data) -> list[str]:
    out = []
    if not isinstance(data, dict) or not isinstance(data.get("targets"), list):
        return ["harvest.json needs an object with a 'targets' list"]
    seen = set()
    for i, t in enumerate(data["targets"]):
        where = f"targets[{i}]"
        if not isinstance(t, dict):
            out.append(f"{where}: not an object"); continue
        k = t.get("kind")
        if k not in KINDS:
            out.append(f"{where}: kind {k!r} not one of {sorted(KINDS)}"); continue
        if k == "reddit" and not re.fullmatch(r"[A-Za-z0-9_]{2,21}", str(t.get("sub", ""))):
            out.append(f"{where}: reddit target needs 'sub' (the subreddit name without r/)")
        elif k == "hn" and not t.get("query"):
            out.append(f"{where}: hn target needs 'query'")
        elif is_gh_query(t):
            pass
        elif k not in ("reddit", "hn") and not str(t.get("url", "")).startswith(("http://", "https://")):
            out.append(f"{where}: {k} target needs an http(s) 'url'")
        if t.get("weight", "normal") not in WEIGHTS:
            out.append(f"{where}: weight must be one of {WEIGHTS}")
        tid = target_id(t)
        if tid in seen:
            out.append(f"{where}: duplicate target {tid}")
        seen.add(tid)
    return out


def merged(units: list[Path]) -> list[dict]:
    """One row per target across units: highest weight wins, keep notes and unit names are collected."""
    rows: dict[str, dict] = {}
    for d in sorted(units, key=lambda p: str(p).lower()):
        try:
            data = load(d)
        except Exception as e:
            print(f"[evergreen] {d / FILE}: {e}", file=sys.stderr); continue
        if not data or problems(data):
            continue
        try:
            name = eg.load_state(d)[1].get("name") or d.name
        except Exception:
            name = d.name
        for t in data["targets"]:
            tid = target_id(t)
            r = rows.setdefault(tid, {"id": tid, "kind": t["kind"], "url": target_url(t), "weight": "low",
                                      "units": [], "keep": []})
            if WEIGHTS.index(t.get("weight", "normal")) > WEIGHTS.index(r["weight"]):
                r["weight"] = t.get("weight", "normal")
            if name not in r["units"]:
                r["units"].append(name)
            if t.get("keep") and t["keep"] not in r["keep"]:
                r["keep"].append(t["keep"])
    return sorted(rows.values(), key=lambda r: (-WEIGHTS.index(r["weight"]), -len(r["units"]), r["id"]))


def cmd_targets(a) -> int:
    roots = [Path(r) for r in a.roots] if a.roots else eg.default_roots()
    units = eg.discover(roots)
    if a.unit:
        units = [u for u in units if u.name == a.unit or str(u) == a.unit or
                 (eg.load_state(u)[1].get("name") == a.unit if (u / "evergreen.json").exists() else False)]
    rows = merged(units)
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False)); return 0
    if not rows:
        print("[evergreen] no unit has a harvest.json yet"); return 0
    for r in rows:
        print(f"{r['weight']:6} {r['id']:32} {', '.join(r['units'])}")
        print(f"       {r['url']}")
        for k in r["keep"]:
            print(f"       keep: {k}")
    print(f"[evergreen] {len(rows)} target(s) from {len({u for r in rows for u in r['units']})} unit(s)")
    return 0


def cmd_lint(a) -> int:
    d = eg.unit_dir(a.unit)
    try:
        data = load(d)
    except Exception as e:
        print(f"[evergreen] {d / FILE}: {e}"); return 1
    if data is None:
        print(f"[evergreen] {d.name}: no {FILE} (optional)"); return 0
    ps = problems(data)
    for p in ps:
        print(f"[evergreen] {d.name}/{FILE}: {p}")
    if not ps:
        print(f"[evergreen] {d.name}/{FILE}: {len(data['targets'])} target(s) ok")
    return 1 if ps else 0


def cmd_add(a) -> int:
    d = eg.unit_dir(a.unit)
    data = load(d) or {"version": 1, "targets": []}
    t = {"kind": a.kind}
    if a.sub: t["sub"] = a.sub.removeprefix("r/")
    if a.url: t["url"] = a.url
    if a.query: t["query"] = a.query
    if a.id: t["id"] = a.id
    if a.weight != "normal": t["weight"] = a.weight
    if a.keep: t["keep"] = a.keep
    tid = target_id(t)
    if any(target_id(x) == tid for x in data["targets"]):
        print(f"[evergreen] {d.name}: {tid} already listed"); return 0
    data["targets"].append(t)
    ps = problems(data)
    if ps:
        for p in ps:
            print(f"[evergreen] {p}")
        return 1
    eg.write_lf(d / FILE, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"[evergreen] {d.name}: added {tid}")
    return 0


def fetch_top(query: str, n: int = 10) -> list[dict]:
    """Top repos by stars for a GitHub search query: `gh api` when gh is installed (authenticated rate limit),
    else the public API, with GITHUB_TOKEN when set."""
    import shutil
    import subprocess
    import urllib.request
    path = "search/repositories?sort=stars&order=desc&per_page=%d&q=%s" % (n, quote(gh_query(query)))
    if shutil.which("gh"):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "gh api failed")
        data = json.loads(r.stdout)
    else:
        req = urllib.request.Request("https://api.github.com/" + path, headers={"Accept": "application/vnd.github+json"})
        if os.environ.get("GITHUB_TOKEN"):
            req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
        with urllib.request.urlopen(req, timeout=30) as f:
            data = json.load(f)
    return [{"repo": i["full_name"], "stars": i["stargazers_count"]} for i in data.get("items", [])[:n]]


def diff_top(prev: list[str], cur: list[dict]) -> list[dict]:
    """Mark each current entry new when it was not in the previous run's list; a first run marks nothing."""
    seen = set(prev)
    return [{**c, "new": bool(prev) and c["repo"] not in seen} for c in cur]


def cmd_top(a, fetch=fetch_top) -> int:
    roots = [Path(r) for r in (getattr(a, "roots", None) or [])] or eg.default_roots()
    found: dict[str, dict] = {}
    for d in eg.discover(roots):
        try:
            data = load(d)
        except Exception:
            continue
        if not data or problems(data):
            continue
        try:
            name = eg.load_state(d)[1].get("name") or d.name
        except Exception:
            name = d.name
        for t in data["targets"]:
            if is_gh_query(t) and (not a.unit or a.unit == name):
                r = found.setdefault(target_id(t), {"query": t["query"], "units": []})
                if name not in r["units"]:
                    r["units"].append(name)
    state_p = Path(a.state) if getattr(a, "state", None) else eg.evergreen_home() / "harvest-top.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    out, bad = [], 0
    for tid, r in sorted(found.items()):
        try:
            cur = fetch(r["query"], a.n)
        except Exception as e:
            print(f"[evergreen] {tid}: {e}", file=sys.stderr); bad += 1; continue
        prev = state.get(tid, {}).get("repos", [])
        out.append({"id": tid, "units": r["units"], "first_run": not prev, "top": diff_top(prev, cur)})
        state[tid] = {"repos": [c["repo"] for c in cur], "date": eg.today().isoformat()}
    if out and not a.no_save:
        state_p.parent.mkdir(parents=True, exist_ok=True)
        eg.write_lf(state_p, json.dumps(state, indent=2) + "\n")
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        for o in out:
            news = sum(c["new"] for c in o["top"])
            print(f"{o['id']}  ({', '.join(o['units'])}; {'first run' if o['first_run'] else f'{news} new'})")
            for c in o["top"]:
                print(f"  {'NEW ' if c['new'] else '    '}{c['stars']:>7}  {c['repo']}")
        if not found:
            print('[evergreen] no github query targets; add one: harvest add <unit> --kind github --query "<topic>"')
    return 1 if bad else 0


def add_parsers(sp, common) -> None:
    s = sp.add_parser("harvest", parents=[common], help="per-unit harvest targets (harvest.json): merged list, lint, add")
    hsp = s.add_subparsers(dest="harvest_cmd", required=True)
    q = hsp.add_parser("targets", help="every unit's targets merged and deduplicated, highest weight first")
    q.add_argument("roots", nargs="*"); q.add_argument("--unit"); q.add_argument("--json", action="store_true")
    q.set_defaults(fn=lambda a: sys.exit(cmd_targets(a)))
    q = hsp.add_parser("lint", help="check one unit's harvest.json"); q.add_argument("unit")
    q.set_defaults(fn=lambda a: sys.exit(cmd_lint(a)))
    q = hsp.add_parser("add", help="add one target to a unit's harvest.json"); q.add_argument("unit")
    q.add_argument("--kind", required=True, choices=sorted(KINDS)); q.add_argument("--sub"); q.add_argument("--url")
    q.add_argument("--query"); q.add_argument("--id"); q.add_argument("--weight", default="normal", choices=WEIGHTS)
    q.add_argument("--keep", help="one line: which posts to keep from this source for this unit")
    q.set_defaults(fn=lambda a: sys.exit(cmd_add(a)))
    q = hsp.add_parser("top", help="top repos by stars for each github query target; new entrants since the last run")
    q.add_argument("roots", nargs="*"); q.add_argument("--unit"); q.add_argument("-n", type=int, default=10)
    q.add_argument("--json", action="store_true"); q.add_argument("--no-save", action="store_true")
    q.add_argument("--state", help="state file (default EVERGREEN_HOME/harvest-top.json)")
    q.set_defaults(fn=lambda a: sys.exit(cmd_top(a)))
