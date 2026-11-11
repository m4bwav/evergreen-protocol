"""Harvest targets: the community places a technique harvest checks for each unit (PROTOCOL.md section 8).

A unit may carry an optional `harvest.json` beside its `evergreen.json`, listing the subreddits, forums, feeds
and pages where practitioners post techniques, tools and workflows that could improve it. A technique harvest
(a periodic sweep that tests the best posts and folds winners into the units) reads the merged list instead of
keeping its own, so the list grows with the units and each unit owns its sources.

    harvest targets [roots...] [--unit U] [--json]   merged, deduplicated list with the units each target feeds
    harvest lint <unit>                              check one unit's harvest.json (exit 1 on a problem)
    harvest add <unit> --kind K (--sub S | --url U | --query Q) [--weight W] [--keep TEXT] [--id ID]

Stdlib only. The file holds public URLs and filter notes, nothing private, so it may live in a public repository.
"""
from __future__ import annotations

import json
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
    return t.get("url", "")


def target_id(t: dict) -> str:
    if t.get("id"):
        return t["id"]
    k = t.get("kind")
    if k == "reddit":
        return f"reddit/{t.get('sub', '').lower()}"
    if k == "hn":
        return "hn/" + re.sub(r"[^a-z0-9]+", "-", t.get("query", "").lower()).strip("-")
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
