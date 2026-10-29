"""The everscout beat offer (PROTOCOL.md section 8, "A beat for a new unit").

When everscout is installed, a new unit is offered a beat once: a community watch on the unit's craft and on how
people use AI for it. A linked beat's notes and radar reports are leads for the unit's refresh, verified against
primary sources before anything changes. State lives in the unit's evergreen.json:

    "scout": {"beat": "<everscout slug>", "status": "linked" | "declined", "date": "YYYY-MM-DD"}

A missing `scout` key means the unit was never asked. `declined` means never ask again. The beat itself lives in
everscout's private beat folder (`everscout.py where`), never in the unit's repository.

Commands: scout detect | offer <unit> | create <unit> | link <unit> --beat <slug> | decline <unit> | leads <unit>
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import evergreen as eg

STATUSES = ("linked", "declined")


# ---------- detection ----------

def _plugin_root_from_skill(skill_dir: Path) -> Path | None:
    try:
        real = skill_dir.resolve()
    except OSError:
        return None
    root = real.parent.parent
    return root if (root / "scripts" / "everscout.py").exists() else None


def detect() -> tuple[Path, str] | None:
    """Where everscout.py is and by which route, or None when everscout is not installed here.
    EVERGREEN_NO_SCOUT=1 forces None (tests, and an owner who wants no offers); EVERSCOUT_PY names the script."""
    if os.environ.get("EVERGREEN_NO_SCOUT") == "1":
        return None
    env = os.environ.get("EVERSCOUT_PY")
    if env:
        p = Path(env).expanduser()
        return (p, "EVERSCOUT_PY") if p.exists() else None
    home = Path.home()
    claude = home / ".claude" / "plugins"
    # 1. a Claude Code plugin install, from any marketplace (mark-local included)
    inst = claude / "installed_plugins.json"
    if inst.exists():
        try:
            plugins = json.loads(inst.read_text(encoding="utf-8")).get("plugins", {})
        except Exception:
            plugins = {}
        for key, rows in plugins.items():
            if key.split("@")[0] != "everscout":
                continue
            for row in rows if isinstance(rows, list) else [rows]:
                p = Path(str(row.get("installPath", ""))) / "scripts" / "everscout.py"
                if p.exists():
                    return p, f"plugin {key}"
    # 2. the plugin cache, newest version first
    cached = sorted(glob.glob(str(claude / "cache" / "*" / "everscout" / "*" / "scripts" / "everscout.py")), key=os.path.getmtime, reverse=True)
    if cached:
        return Path(cached[0]), "plugin cache"
    # 3. a local marketplace that lists everscout by path
    for mp in glob.glob(str(claude / "marketplaces" / "*" / ".claude-plugin" / "marketplace.json")):
        try:
            entries = json.loads(Path(mp).read_text(encoding="utf-8")).get("plugins", [])
        except Exception:
            continue
        for e in entries:
            src = e.get("source")
            if e.get("name") == "everscout" and isinstance(src, str):
                p = (Path(mp).parent.parent / src).resolve() / "scripts" / "everscout.py"
                if p.exists():
                    return p, f"marketplace {Path(mp).parent.parent.name}"
    # 4. exported skills (~/.agents/skills/everscout-*, often junctions to the plugin's skills)
    for sk in sorted(glob.glob(str(home / ".agents" / "skills" / "everscout-*"))):
        root = _plugin_root_from_skill(Path(sk))
        if root:
            return root / "scripts" / "everscout.py", "exported skills"
    # 5. an everscout unit in the evergreen registry
    for u in eg.load_registry().get("units", []):
        if str(u.get("name", "")).startswith("everscout"):
            root = _plugin_root_from_skill(Path(u.get("path", "")))
            if root:
                return root / "scripts" / "everscout.py", "evergreen registry"
    return None


def run_es(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, encoding="utf-8")


# ---------- the offer ----------

def description_of(d: Path, st: dict) -> str:
    main = d / st.get("main", "SKILL.md")
    if not main.exists():
        return ""
    m = re.search(r"^description:\s*\"?(.+?)\"?\s*$", main.read_text(encoding="utf-8")[:4000], re.M)
    return m.group(1) if m else ""


def what_it_does(d: Path, st: dict) -> str:
    desc = description_of(d, st)
    first = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0] if desc else ""
    craft = (st.get("topic") or first or st.get("name", "this unit"))
    craft = re.split(r"[:;(]", craft, maxsplit=1)[0].strip()  # the head of a long topic line reads as a craft
    return (craft[:90].rsplit(" ", 1)[0] if len(craft) > 90 else craft).rstrip(".,")


def plan(d: Path, st: dict, craft: str | None = None) -> dict:
    craft = craft or what_it_does(d, st)
    slug = re.sub(r"[^a-z0-9]+", "-", st["name"].lower()).strip("-")
    return {
        "slug": slug,
        "title": f"{st['name']}: {craft}"[:120],
        "question": f"Want me to set up an everscout beat on {craft} and how people use AI to do it? "
                    f"Its findings would feed {st['name']}'s refresh cycle.",
        "scope": f"Follows {craft}: what practitioners are doing now, and how people use AI for it. "
                 f"Feeds the evergreen unit {st['name']}'s refresh as leads, verified against primary sources.",
        "questions": [
            f"What are practitioners of {craft} doing now: methods, tools, debates and what changed lately?",
            f"How are people using AI for {craft}: tools, workflows, prompts, what works and what they complain about?",
        ],
    }


def set_scout(d: Path, st: dict, status: str, beat: str | None = None) -> dict:
    st["scout"] = {"beat": beat, "status": status, "date": eg.today().isoformat()}
    eg.save_state(d, st)
    return st["scout"]


def cmd_detect(a) -> int:
    found = detect()
    if a.json:
        print(json.dumps({"installed": bool(found), "script": str(found[0]) if found else None, "route": found[1] if found else None}))
    elif found:
        print(f"everscout: {found[0]} ({found[1]})")
    else:
        print("everscout: not installed")
    return 0 if found else 1


def cmd_offer(a) -> int:
    """Exit 0 and print the question when the offer should be made; exit 1 (silent unless --why) otherwise."""
    d, st = eg.load_state(a.unit)
    found = detect()
    why = None
    if not found:
        why = "everscout is not installed: say nothing"
    elif (st.get("scout") or {}).get("status") in STATUSES:
        why = f"already {st['scout']['status']} on {st['scout'].get('date')}"
    elif st.get("kind") not in ("skill", "plugin", "doc"):
        why = f"kind {st.get('kind')} gets no beat"
    elif st.get("tier") == "none":
        why = "tier none has no research to feed"
    if why:
        if a.why or a.json:
            print(json.dumps({"offer": False, "why": why}) if a.json else why)
        return 1
    p = plan(d, st, a.craft)
    if a.json:
        print(json.dumps(dict(p, offer=True)))
    else:
        print(p["question"])
        print(f"  yes: evergreen.py scout create {d.resolve()}    no: evergreen.py scout decline {d.resolve()}")
    return 0


def cmd_create(a) -> int:
    d, st = eg.load_state(a.unit)
    found = detect()
    if not found:
        print("everscout is not installed; nothing created")
        return 1
    p = plan(d, st, a.craft)
    slug = a.slug or p["slug"]
    args = ["beat-new", slug, "--title", a.title or p["title"], "--scope", p["scope"], "--feeds", f"evergreen:{st['name']}"]
    for q in p["questions"]:
        args += ["--question", q]
    r = run_es(found[0], *args)
    if r.returncode != 0 and "exists" not in (r.stderr + r.stdout):
        print(f"beat-new failed: {(r.stderr or r.stdout).strip()}")
        return 1
    where = run_es(found[0], "where", "--beat", slug)
    beat_dir = next((ln.split("=", 1)[1].strip() for ln in where.stdout.splitlines() if ln.startswith("BEAT")), None)
    if not beat_dir:
        print(f"beat {slug} was not found after beat-new: {(where.stderr or where.stdout).strip()}")
        return 1
    set_scout(d, st, "linked", slug)
    print(f"beat {slug} at {beat_dir}; linked in {d / 'evergreen.json'}")
    print("next: everscout-beat procedure A from step 3 (find and verify sources), then beat-check and probe")
    return 0


def cmd_link(a) -> int:
    d, st = eg.load_state(a.unit)
    found = detect()
    if not found:
        print("everscout is not installed; nothing linked")
        return 1
    r = run_es(found[0], "where", "--beat", a.beat)
    if r.returncode != 0:
        print(f"no beat {a.beat}: {(r.stderr or r.stdout).strip()}")
        return 1
    set_scout(d, st, "linked", a.beat)
    print(f"linked {st['name']} to beat {a.beat}")
    return 0


def cmd_decline(a) -> int:
    d, st = eg.load_state(a.unit)
    set_scout(d, st, "declined")
    print(f"{st['name']}: beat declined; it will not be offered again (`scout offer` stays silent)")
    return 0


def cmd_leads(a) -> int:
    """The beat's notes and reports since the unit's last_checked, and whether a scan should run first."""
    d, st = eg.load_state(a.unit)
    sc = st.get("scout") or {}
    if sc.get("status") != "linked" or not sc.get("beat"):
        print(f"{st['name']}: no linked beat")
        return 1
    found = detect()
    if not found:
        print(f"{st['name']}: linked to beat {sc['beat']}, but everscout is not installed here; research without leads")
        return 1
    since = a.since or st.get("last_checked") or "1970-01-01"
    r = run_es(found[0], "leads", "--beat", sc["beat"], "--since", since, "--json", "--limit", str(a.limit))
    if r.returncode != 0:
        print(f"leads failed: {(r.stderr or r.stdout).strip()}")
        return 1
    data = json.loads(r.stdout)
    interval = float(st.get("interval_days") or 14)
    lf = data.get("last_fetch")
    age = None
    if lf:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(lf.replace("Z", "+00:00"))).days
        except ValueError:
            age = None
    scan_first = lf is None or (age is not None and age > interval)
    data["scan_first"] = scan_first
    if a.json:
        print(json.dumps(data, indent=1))
        return 0
    print(f"beat {sc['beat']}: {data['notes_total']} notes, {len(data['reports'])} reports since {since}; last scan {lf or 'never'}")
    if scan_first:
        print(f"scan first: run everscout-scan on {sc['beat']} (last scan is older than the unit's {interval:g}-day interval)")
    for rep in data["reports"][:3]:
        print(f"report {rep['date']} {rep['path']}: {rep['summary'][:160]}")
    for n in data["notes"]:
        print(f"note   {n['date']} {n['title'][:90]} {n['url']}")
    print("these are leads: verify each against a primary source; cite that source, and name the beat leads in the refresh log")
    return 0


def add_parsers(sp, common) -> None:
    s = sp.add_parser("scout", parents=[common], help="the everscout beat offer: detect, offer, create, link, decline, leads")
    ssp = s.add_subparsers(dest="scout_cmd", required=True)
    q = ssp.add_parser("detect", help="is everscout installed here, and where (exit 1 when not)"); q.add_argument("--json", action="store_true")
    q.set_defaults(fn=lambda a: sys.exit(cmd_detect(a)))
    q = ssp.add_parser("offer", help="print the one-time offer for a unit (exit 1, silent, when it should not be made)"); q.add_argument("unit")
    q.add_argument("--why", action="store_true", help="say why no offer is made"); q.add_argument("--json", action="store_true")
    q.add_argument("--craft", help="what the unit does, in a few words (default: the head of its topic)")
    q.set_defaults(fn=lambda a: sys.exit(cmd_offer(a)))
    q = ssp.add_parser("create", help="on yes: scaffold the beat with the unit's scope and link it"); q.add_argument("unit")
    q.add_argument("--slug"); q.add_argument("--title"); q.add_argument("--craft"); q.set_defaults(fn=lambda a: sys.exit(cmd_create(a)))
    q = ssp.add_parser("link", help="link an existing beat to a unit"); q.add_argument("unit"); q.add_argument("--beat", required=True)
    q.set_defaults(fn=lambda a: sys.exit(cmd_link(a)))
    q = ssp.add_parser("decline", help="on no: record it so the unit is never asked again"); q.add_argument("unit")
    q.set_defaults(fn=lambda a: sys.exit(cmd_decline(a)))
    q = ssp.add_parser("leads", help="the linked beat's notes and reports since last_checked, for a refresh"); q.add_argument("unit")
    q.add_argument("--since"); q.add_argument("--limit", type=int, default=25); q.add_argument("--json", action="store_true")
    q.set_defaults(fn=lambda a: sys.exit(cmd_leads(a)))
