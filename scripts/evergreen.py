#!/usr/bin/env python3
"""evergreen.py - state and scheduling helper for the Evergreen Protocol.

Pure standard library. Every command fails soft (prints a note, exits 0) so
it is safe to run from a session-start hook; add --strict to exit non-zero.

Commands
  home                              print EVERGREEN_HOME
  status  <unit>                    one-line freshness report
  audit   [--brief] [--json] [--checks] [--roots P ...]   all known units
  next    <unit> --m 0.4            dry-run the interval rule
  checked <unit> --m 0.4 [--note ..] [--contradiction] [--use-time]
                                    record a refresh; compute next_due
  flag    <unit> [--contradiction "why"] [--clear-contradiction]
                 [--event 2026-11-15:label:2] [--clear-failing [ID ...]]
  init    <dir> --name N --topic T [--kind skill] [--tier moderate]
                [--main SKILL.md] [--standalone] [--append-maintenance]
                [--source PATH] [--last-checked DATE]   scaffold + state
  test-init <unit>                  add TESTS.md, evals/evals.json and the tests block to an existing skill or plugin
  tested  <unit> --passed N --failed N [--failing id,id] [--harness H] [--env E] [--note ..]
                                    record a suite run; prints the next T- id for TESTS.md
  failed  <unit> --case ID --class CLASS [--note ..]   record a failure seen in use; says whether research is due first
  use-log                           PostToolUse hook body (stdin JSON): append a Skill use to EVERGREEN_HOME/uses.jsonl
  uses    [--skill NAME] [--days 7] [--limit 20] [--json]   recent skill uses, newest first
  map-slug <repo>                   slug for a repo path
  map-init <repo> [--name N]        create a codemap unit in the store
  drift   <map-unit> [--update-sha] commits/files changed since stamped sha
  links   <unit>                    verify double links and entry IDs
  lint    <unit>                    budgets, learnings fields, consolidation
  register <unit> | unregister <unit>
  bump    <unit> --learnings|--changes|--research|--tests
  export  <repo>                    copy the plugin into <repo>/.agents/ for non-Claude agents
  pack    [--out DIR] [--mail] [--split KB] [--no-git]   build evergreen-<version>.zip, .plugin, INSTALL-PROMPT (+ MANIFEST.json, baseline,
                                    git commit + tag when the plugin folder is a repo); --mail = Gmail-safe zip
  unmail  <folder>                  restore script names after unzipping a --mail archive
  where                             plugin root, store, env name, baseline, git, notify readiness
  publish [--dry-run] [--branch]    commit and push the plugin's self-changes: trunk branch as maintainer, else branch + PR (evergreen_sync.py)
  pull                              fast-forward this clone from the trunk repository (evergreen_sync.py)
  baseline [--from ZIP]             snapshot this install as the base for diff (evergreen_sync.py)
  diff    [--out DIR] [--stdout]    update bundle: UPDATE.md + changes.patch + manifest.json in EVERGREEN_HOME/outbox
  notify  [--if-changed] [--detach] [--transport T] [--dry-run] [--mark-sent DIR --via NAME]
                                    email the bundle to notify.to (evergreen.config.json) via outlook | graph | smtp
  merge   <bundle|patch|email.txt> [--trunk DIR] [--dry-run]   fold an update into the trunk

<unit> is a directory containing evergreen.json (or the json file itself).
A unit's protocol may be the literal "plugin": it then resolves to the one installed plugin (this file's root, or
registry.json's plugin_root), so units do not change when the plugin does.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

PROTOCOL_VERSION = "1.0"

# tier: (min_days, max_days, start_days)
TIERS = {
    "live": (0.25, 3, 1),
    "fast": (3, 21, 14),
    "moderate": (14, 90, 30),
    "slow": (60, 365, 120),
    "glacial": (270, 900, 365),
    "code": (7, 90, 30),
    "none": (None, None, None),
}
TIER_ORDER = ["live", "fast", "moderate", "slow", "glacial"]  # fastest -> slowest; code and none never migrate
JITTER = 0.15
BUDGETS = {"main": 200, "main_hard": 500, "learnings": 200, "codemap": 150, "understanding": 60, "tests": 150}
ID_RE = re.compile(r"(?<![\w.:-])(R-\d{8}-\d+|C-\d{8}-\d+|T-\d{8}-\d+|L-\d{3,})\b")  # `other-unit:L-003` is a qualified cross-unit reference, not checked here
DEF_RE = re.compile(r"^#{2,6}\s*(R-\d{8}-\d+|C-\d{8}-\d+|T-\d{8}-\d+|L-\d{3,})\b", re.M)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PACK_EXCLUDE = {".git", "__pycache__", ".DS_Store", "node_modules", ".pytest_cache"}
TESTED_KINDS = ("skill", "plugin")  # kinds that carry a test suite (TESTS.md + evals/evals.json + a `tests` block)
TEST_FILES = {"TESTS.md": "TESTS.md.template", "evals/evals.json": "evals.json.template"}
FAILURE_CLASSES = ("undertrigger", "overtrigger", "no-op", "fallback", "wrong-outcome", "environment", "harness")
RESEARCH_FIRST_CLASSES = ("no-op", "fallback")  # a failure of these classes sends the agent to research before tuning
SEARCH_TRACKS = ("subject", "tooling", "practice", "testing")


# ---------- paths and io ----------

def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _looks_windows(p: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", p))


def evergreen_home() -> Path:
    """EVERGREEN_HOME env var > evergreen.config.json {"home": str | {"nt": .., "posix": ..}} > ~/.evergreen.
    A Windows drive-letter path is ignored on non-Windows hosts (it would become a relative dir)."""
    env = os.environ.get("EVERGREEN_HOME")
    if env and not (os.name != "nt" and _looks_windows(env)):
        return _usable_home(Path(os.path.expandvars(env)).expanduser())
    cfg = plugin_root() / "evergreen.config.json"
    if cfg.exists():
        try:
            home = json.loads(cfg.read_text(encoding="utf-8")).get("home")
            if isinstance(home, dict):
                home = home.get(os.name) or home.get("default")
            if home and not (os.name != "nt" and _looks_windows(str(home))):
                return _usable_home(Path(os.path.expandvars(str(home))).expanduser())
        except Exception:
            pass
    return Path.home() / ".evergreen"


_home_warned = False


def _usable_home(p: Path) -> Path:
    """A configured store on a drive this machine does not have (the shipped config names the trunk's D:) falls
    back to ~/.evergreen with one note, instead of failing every command that touches the registry."""
    global _home_warned
    anchor = Path(p.anchor) if p.anchor else None
    if anchor and not anchor.exists():
        if not _home_warned:
            print(f"[evergreen] store {p} is on a drive that does not exist here; using ~/.evergreen (set EVERGREEN_HOME to choose)", file=sys.stderr)
            _home_warned = True
        return Path.home() / ".evergreen"
    return p


def unit_dir(p: str | Path) -> Path:
    p = Path(p).expanduser()
    if p.is_file() and p.name == "evergreen.json":
        return p.parent
    return p


def load_state(unit: str | Path) -> tuple[Path, dict]:
    d = unit_dir(unit)
    f = d / "evergreen.json"
    if not f.exists():
        raise FileNotFoundError(f"no evergreen.json in {d}")
    return d, json.loads(f.read_text(encoding="utf-8"))


def save_state(d: Path, st: dict) -> None:
    (d / "evergreen.json").write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def today() -> date:
    return date.today()


def parse_when(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s), fmt)
        except ValueError:
            continue
    return None


def fmt_when(dt: datetime, hours: bool = False) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M") if hours else dt.strftime("%Y-%m-%d")


def fmt_days(x: float | None) -> str:
    if x is None:
        return "n/a"
    if x < 1:
        return f"{x * 24:.0f}h"
    return f"{x:.0f}d" if abs(x - round(x)) < 0.05 else f"{x:.1f}d"


def strip_comments(txt: str) -> str:
    return COMMENT_RE.sub("", txt)


def env_default() -> str:
    """Name of this environment: EVERGREEN_ENV, else the config's env_name (evergreen_sync), else the hostname."""
    name = os.environ.get("EVERGREEN_ENV")
    if not name:
        try:
            import evergreen_sync as es
            return es.env_name()
        except Exception:
            try:
                name = socket.gethostname()
            except Exception:
                name = "unknown"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-") or "unknown"


def uses_path() -> Path:
    return evergreen_home() / "uses.jsonl"


# ---------- registry ----------

def registry_path() -> Path:
    return evergreen_home() / "registry.json"


def load_registry() -> dict:
    p = registry_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "units": []}


def save_registry(reg: dict) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def register(unit: Path, st: dict) -> None:
    reg = load_registry()
    path = str(unit.resolve())
    entry = {"name": st.get("name"), "path": path, "kind": st.get("kind"), "tier": st.get("tier"), "source": st.get("source")}
    reg["units"] = [u for u in reg["units"] if u.get("path") != path]
    reg["units"].append(entry)
    if st.get("kind") == "plugin":
        reg["plugin_root"] = path  # what `protocol: "plugin"` units resolve to
    save_registry(reg)


def resolve_protocol(d: Path, st: dict) -> Path | None:
    """Path of the protocol a unit follows. 'plugin' means the installed plugin (pointer mode)."""
    proto = str(st.get("protocol") or "")
    if not proto:
        return None
    if proto == "plugin":
        env = os.environ.get("EVERGREEN_PLUGIN")
        roots = ([Path(os.path.expandvars(env)).expanduser()] if env else []) + [plugin_root(), Path(str(load_registry().get("plugin_root") or ""))]
        for root in roots:
            p = root / "protocol" / "PROTOCOL.md"
            if p.exists():
                return p
        return None
    if proto.startswith("$"):
        return None
    for cand in (d / proto, Path(proto)):
        if cand.exists():
            return cand
    return None


def unregister(unit: Path) -> None:
    reg = load_registry()
    path = str(unit.resolve())
    reg["units"] = [u for u in reg["units"] if u.get("path") != path]
    save_registry(reg)


# ---------- interval rule (protocol/INTERVALS.md) ----------

def bounds_for(st: dict) -> tuple[float | None, float | None, float | None]:
    tier = st.get("tier", "moderate")
    mn, mx, start = TIERS.get(tier, TIERS["moderate"])
    b = st.get("bounds_days") or {}
    return (b.get("min", mn), b.get("max", mx), start)


def _migrate(st: dict, new_tier: str, report: list, why: str) -> tuple[float, float]:
    st["tier"] = new_tier
    if st.pop("bounds_days", None):
        report.append("custom bounds_days dropped on tier change")
    mn, mx, _ = TIERS[new_tier]
    report.append(f"{why} -> tier {new_tier}")
    return mn, mx


def compute_next(st: dict, m: float | None, now: datetime, contradiction: bool = False, use_time: bool = False,
                 jitter: bool = True) -> dict:
    """Apply the interval rule to a copy of the state; returns it with a 'report' key."""
    st = json.loads(json.dumps(st))  # deep copy
    tier = st.get("tier", "moderate")
    report: list[str] = []
    streak = st.setdefault("streak", {"quiet": 0, "pinned_min": 0, "pinned_max": 0, "vau_quiet": 0})
    hist_entry: dict = {"date": fmt_when(now, tier == "live"), "m": m}

    if tier == "none":
        st["last_checked"] = fmt_when(now)
        st["next_due"] = None
        hist_entry["interval_after"] = None
        st.setdefault("history", []).append(hist_entry)
        st["report"] = "tier none: no research schedule"
        return st

    mn, mx, start = bounds_for(st)
    I = float(st.get("interval_days") or start)
    had_contradiction = bool(st.get("contradiction")) or contradiction

    if m is None:  # failed refresh: keep the schedule, log the attempt
        hist_entry["interval_after"] = I
        hist_entry["note"] = "refresh failed; schedule unchanged"
        st.setdefault("history", []).append(hist_entry)
        st["report"] = "refresh failed; next_due unchanged"
        return st

    if use_time and st.get("verify_at_use"):
        streak["vau_quiet"] = streak.get("vau_quiet", 0) + 1 if m == 0 else 0
        st["last_checked"] = fmt_when(now)
        if streak["vau_quiet"] >= 2:
            st["verify_at_use"] = False
            st["tier"] = "fast"
            I = TIERS["fast"][2]
            streak["vau_quiet"] = 0
            st["interval_days"] = I
            st["next_due"] = fmt_when(now + timedelta(days=I))
            report.append("verify_at_use off after 2 quiet use-time checks; back to fast")
        hist_entry["interval_after"] = st.get("interval_days") if not st.get("verify_at_use") else None
        hist_entry["note"] = "use-time check"
        st.setdefault("history", []).append(hist_entry)
        st["report"] = "; ".join(report) or "use-time check recorded"
        return st

    idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else None

    if had_contradiction:
        I = mn
        report.append("contradiction: interval reset to min")
    elif m >= 0.6:
        I = I / 4
        report.append("major change: interval / 4")
        # immediate promotion: a major change that would clamp below min moves one tier faster now
        if idx is not None and idx > 0 and I < mn and tier not in ("fast", "live"):
            new_tier = TIER_ORDER[idx - 1]
            mn, mx = _migrate(st, new_tier, report, "major change below tier min")
            idx -= 1
            I = max(mn, I)
            streak["pinned_min"] = 0
    elif m >= 0.3:
        I = I / 2
        report.append("change: interval / 2")
    elif m > 0:
        report.append("minor churn: interval held")
    else:
        I = I * 1.5
        report.append("quiet: interval x 1.5")

    eps = 1e-6
    clamped_min = I <= mn + eps
    clamped_max = I >= mx - eps
    I = max(mn, min(mx, I))

    # streaks
    streak["quiet"] = streak.get("quiet", 0) + 1 if m == 0 else 0
    streak["pinned_min"] = streak.get("pinned_min", 0) + 1 if (clamped_min and m >= 0.3) else 0
    streak["pinned_max"] = streak.get("pinned_max", 0) + 1 if (clamped_max and m == 0) else 0

    # streak-based migration
    if idx is not None:
        if st["tier"] in ("fast", "live") and streak["pinned_min"] >= 3:
            st["verify_at_use"] = True
            streak["pinned_min"] = 0
            report.append("pinned at min 3x: verify_at_use ON (re-check volatile_claims at every use; no calendar)")
        elif st["tier"] not in ("fast", "live") and streak["pinned_min"] >= 2:
            new_tier = TIER_ORDER[idx - 1]
            mn, mx = _migrate(st, new_tier, report, "pinned at min 2x")
            I = mn
            streak["pinned_min"] = 0
        elif streak["pinned_max"] >= 3 and idx < len(TIER_ORDER) - 1:
            new_tier = TIER_ORDER[idx + 1]
            mn, mx = _migrate(st, new_tier, report, "pinned at max 3x quiet")
            I = max(mn, min(mx, I))
            streak["pinned_max"] = 0

    st["interval_days"] = round(I, 2)
    hours = st.get("tier") == "live"
    st["last_checked"] = fmt_when(now, hours)
    st["contradiction"] = None

    if st.get("verify_at_use"):
        st["next_due"] = None
        hist_entry["interval_after"] = None
        st.setdefault("history", []).append(hist_entry)
        st["report"] = "; ".join(report)
        return st

    eff = I * (1 + random.uniform(-JITTER, JITTER)) if jitter else I
    due = now + timedelta(days=eff)

    # known events cap next_due (never extend it); past events are dropped
    kept = []
    for ev in st.get("events", []) or []:
        ed = parse_when(ev.get("date"))
        if not ed:
            continue
        settle = float(ev.get("settle_days", 2))
        if ed + timedelta(days=settle) < now:
            continue
        kept.append(ev)
        cap = ed + timedelta(days=settle)
        if ed > now and cap < due:
            due = cap
            report.append(f"capped by event '{ev.get('label', '')}' -> {fmt_when(cap)}")
    st["events"] = kept

    st["next_due"] = fmt_when(due, hours)
    hist_entry["interval_after"] = st["interval_days"]
    st.setdefault("history", []).append(hist_entry)
    st["report"] = "; ".join(report)
    return st


# ---------- status ----------

def freshness(st: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    out = {"name": st.get("name"), "kind": st.get("kind"), "tier": st.get("tier"), "last": st.get("last_checked"),
           "due": st.get("next_due"), "status": "fresh", "flags": []}
    if st.get("contradiction"):
        out["flags"].append("contradiction")
        out["status"] = "STALE"
        return out
    if st.get("verify_at_use"):
        out["flags"].append("verify-at-use")
        out["status"] = "n/a"
        return out
    if st.get("tier") == "none":
        out["status"] = "n/a"
        return out
    due = parse_when(st.get("next_due"))
    if due is None:
        out["status"] = "STALE"
        out["flags"].append("no next_due")
    elif now >= due:
        out["status"] = "STALE"
        out["overdue_days"] = round((now - due).total_seconds() / 86400, 1)
    else:
        out["due_in_days"] = round((due - now).total_seconds() / 86400, 1)
    return out


# ---------- tests (protocol/TESTING.md) ----------

def new_tests_block() -> dict:
    return {"last_run": None, "harness": None, "env": None, "cases": 0, "passed": 0, "failed": 0, "failing": [],
            "last_failure": None, "research_after_days": None}


def tests_apply(st: dict) -> bool:
    return st.get("kind") in TESTED_KINDS


def research_after(st: dict) -> float:
    """Days since last_checked after which a failure sends the agent to research before tuning:
    tests.research_after_days, or half the interval clamped to [3, 30]."""
    v = (st.get("tests") or {}).get("research_after_days")
    if v is not None:
        return float(v)
    return max(3.0, min(30.0, float(st.get("interval_days") or 30) / 2))


def test_flags(st: dict, now: datetime | None = None) -> list[str]:
    """Flags that never change the freshness status: failing-tests:n, untested, tests-overdue."""
    t = st.get("tests")
    if not isinstance(t, dict):
        return []
    now = now or datetime.now()
    out = []
    if t.get("failing"):
        out.append(f"failing-tests:{len(t['failing'])}")
    lr = parse_when(t.get("last_run"))
    if not t.get("last_run"):
        out.append("untested")
    elif lr and st.get("tier") != "none" and (now - lr).total_seconds() / 86400 > 2 * float(st.get("interval_days") or 0):
        out.append("tests-overdue")
    return out


def next_entry_id(d: Path, st: dict, prefix: str = "T", when: date | None = None) -> str:
    """Next dated id for a log entry: <prefix>-<YYYYMMDD>-<n>, n = 1 + heads already carrying today's date."""
    fname = {"T": "tests", "R": "research", "C": "changelog"}.get(prefix, "tests")
    p = d / ((st.get("files") or {}).get(fname) or {"T": "TESTS.md", "R": "RESEARCH.md", "C": "CHANGELOG.md"}[prefix])
    day = (when or today()).strftime("%Y%m%d")
    n = 0
    if p.exists():
        n = len(re.findall(rf"^#{{2,6}}\s*{prefix}-{day}-\d+\b", p.read_text(encoding="utf-8", errors="replace"), flags=re.M))
    return f"{prefix}-{day}-{n + 1}"


def research_verdict(st: dict, cls: str, now: datetime | None = None) -> str:
    """After a failure: research first (the world may have moved) or tune directly."""
    now = now or datetime.now()
    th = research_after(st)
    lc = parse_when(st.get("last_checked"))
    age = (now - lc).total_seconds() / 86400 if lc else None
    n = str(int(age)) if age is not None else "never"
    if st.get("tier") == "none":
        return "research not due (tier none: no research schedule); tune directly"
    if age is None or age > th or cls in RESEARCH_FIRST_CLASSES:
        tag = f"; class {cls} asks for research first" if cls in RESEARCH_FIRST_CLASSES else ""
        return f"research due: last checked {n} days ago (threshold {fmt_days(th)}{tag}); run evergreen-refresh with the testing track first, then tune"
    return f"research not due (checked {n} days ago, threshold {fmt_days(th)}); tune directly"


def evals_problems(p: Path) -> list[str]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"evals/evals.json: not valid JSON ({e})"]
    cases = data.get("evals") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        return ["evals/evals.json: no 'evals' list"]
    cases = [c for c in cases if isinstance(c, dict)]
    out = []
    if not any(c.get("kind") == "action" for c in cases):
        out.append('evals/evals.json: no case with "kind": "action" (nothing proves the skill acted; PROTOCOL §11)')
    if not any(c.get("decoy") is True for c in cases):
        out.append('evals/evals.json: no decoy case ("decoy": true; nothing checks it stays quiet)')
    todo = [str(c.get("id") or f"#{i + 1}") for i, c in enumerate(cases) if "TODO" in str(c.get("prompt", ""))]
    if todo:
        out.append(f"evals/evals.json: TODO prompts still in {', '.join(todo)}")
    return out


def source_state(d: Path, st: dict) -> str | None:
    """'installed-copy' when the source exists elsewhere; 'source-unreachable' when set but not visible; else None."""
    if not st.get("source"):
        return None
    sp = Path(str(st["source"]))
    if os.name != "nt" and _looks_windows(str(st["source"])):
        return "source-unreachable"
    if not sp.exists():
        return "source-unreachable"
    return "installed-copy" if sp.resolve() != d.resolve() else None


def status_line(d: Path, st: dict, fr: dict, verbose: bool = False) -> str:
    flags = (" [" + ",".join(fr["flags"]) + "]") if fr["flags"] else ""
    extra = ""
    if "overdue_days" in fr:
        extra = f" overdue {fr['overdue_days']}d"
    elif "due_in_days" in fr:
        extra = f" due in {fr['due_in_days']}d"
    src = source_state(d, st)
    tag = ""
    if src == "installed-copy":
        tag = " (installed copy; edit source)"
    elif src == "source-unreachable" and verbose:
        tag = " (source not visible from here; mounted or sandboxed?)"
    return f"{fr['name']:<32} {str(fr['kind']):<8} {str(fr['tier']):<9} last {str(fr['last']):<10} due {str(fr['due']):<16} {fr['status']}{extra}{flags}{tag}"


# ---------- discovery ----------

def default_roots() -> list[Path]:
    home = evergreen_home()
    roots = [plugin_root(), home / "units", home / "maps", Path.cwd(),
             Path.home() / ".claude" / "skills", Path.cwd() / ".claude" / "skills",
             Path.home() / ".agents" / "skills", Path.cwd() / ".agents" / "skills"]
    seen, out = set(), []
    for r in roots:
        try:
            k = str(r.resolve())
        except Exception:
            continue
        if k not in seen and r.exists():
            seen.add(k)
            out.append(r)
    return out


def discover(roots: list[Path], max_depth: int = 4) -> list[Path]:
    found: dict[str, Path] = {}
    for u in load_registry().get("units", []):
        p = Path(u.get("path", ""))
        if (p / "evergreen.json").exists():
            found[str(p.resolve())] = p
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "Library", "site-packages"}
    for root in roots:
        root = Path(root)
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [x for x in dirnames if (x not in skip and not x.startswith(".")) or x in (".claude", ".agents")]
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
            if "evergreen.json" in filenames:
                p = Path(dirpath)
                found.setdefault(str(p.resolve()), p)
    return list(found.values())


# ---------- codemaps ----------

def git(args: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except Exception:
        return None


def map_slug(repo: Path) -> str:
    repo = repo.resolve()
    remote = git(["config", "--get", "remote.origin.url"], repo)
    if remote:
        s = re.sub(r"\.git$", "", remote.strip())
        s = re.sub(r"^.*[:/]([^/]+)/([^/]+)$", r"\1--\2", s)
        s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)
        return s
    h = hashlib.sha1(str(repo).encode("utf-8")).hexdigest()[:6]
    return f"{repo.name}-{h}"


def drift(st: dict) -> dict:
    repo = st.get("repo") or {}
    root, sha = repo.get("root"), repo.get("sha")
    out = {"commits": None, "files_changed": None, "files_total": None, "stale": False, "note": ""}
    if not root or not sha:
        out["note"] = "no repo root/sha recorded"
        return out
    if not Path(root).exists():
        out["note"] = "repo root not visible from here"
        return out
    rp = Path(root)
    c = git(["rev-list", "--count", f"{sha}..HEAD"], rp)
    if c is None:
        out["note"] = "git unavailable or sha unknown"
        return out
    out["commits"] = int(c)
    changed = git(["diff", "--name-only", f"{sha}..HEAD"], rp) or ""
    total = git(["ls-files"], rp) or ""
    out["files_changed"] = len([x for x in changed.splitlines() if x.strip()])
    out["files_total"] = max(1, len([x for x in total.splitlines() if x.strip()]))
    th = repo.get("drift") or {"commits": 30, "files_pct": 20}
    pct = 100.0 * out["files_changed"] / out["files_total"]
    out["files_pct"] = round(pct, 1)
    if out["commits"] >= th.get("commits", 30) or pct >= th.get("files_pct", 20):
        out["stale"] = True
    return out


# ---------- templates ----------

def render(template: str, subs: dict) -> str:
    for k, v in subs.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def scaffold_subs(st: dict, kind: str) -> dict:
    lc = str(st.get("last_checked") or today())[:10]
    proto = str(st.get("protocol") or "")
    return {"NAME": st.get("name", ""), "TOPIC": st.get("topic", ""), "DATE": lc, "DATEID": lc.replace("-", ""), "TIER": st.get("tier", ""),
            "MAIN": st.get("main", "SKILL.md"), "PROTOCOL": "MAINTENANCE.md" if proto == "plugin" else proto,
            "INTERVAL": fmt_days(st.get("interval_days")), "NEXT_DUE": st.get("next_due") or "n/a", "KIND": kind,
            "SHA": str((st.get("repo") or {}).get("sha") or "n/a"), "REPO": str((st.get("repo") or {}).get("root") or "")}


def write_templates(d: Path, files: dict, subs: dict) -> list[str]:
    """Render {out_name: template_name} into d, keeping files that already exist. Returns notes."""
    tdir = plugin_root() / "templates"
    notes = []
    for out_name, t_name in files.items():
        out = d / out_name
        t = tdir / t_name
        if out.exists():
            notes.append(f"kept existing {out_name}")
            continue
        if not t.exists():
            notes.append(f"missing template {t_name}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(t.read_text(encoding="utf-8"), subs), encoding="utf-8")
        notes.append(f"wrote {out_name}")
    return notes


def scaffold(d: Path, st: dict, standalone: bool, append_maintenance: bool, kind: str, pointer: bool = False) -> list[str]:
    tdir = plugin_root() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    subs = scaffold_subs(st, kind)
    files = {"RESEARCH.md": "RESEARCH.md.template", "CHANGELOG.md": "CHANGELOG.md.template",
             "LEARNINGS.md": "LEARNINGS.md.template"}
    if kind == "map":
        files = {"CODEMAP.md": "CODEMAP.md.template", "CHANGELOG.md": "CHANGELOG-MAP.md.template",
                 "LEARNINGS.md": "LEARNINGS-MAP.md.template"}
    if pointer:
        files["MAINTENANCE.md"] = "MAINTENANCE-POINTER.md.template"
    elif standalone:
        files["MAINTENANCE.md"] = "MAINTENANCE.md.template"
    if kind in TESTED_KINDS:
        files.update(TEST_FILES)
    notes = write_templates(d, files, subs)
    main = d / st["main"]
    if kind != "map":
        if not main.exists():
            t = tdir / "SKILL.md.template"
            if t.exists():
                main.write_text(render(t.read_text(encoding="utf-8"), subs), encoding="utf-8")
                notes.append(f"wrote {st['main']} from template (edit it)")
        elif append_maintenance:
            t = tdir / "MAINTENANCE-SECTION.md.template"
            txt = main.read_text(encoding="utf-8")
            if "evergreen.json" not in txt and t.exists():
                main.write_text(txt.rstrip("\n") + "\n\n" + render(t.read_text(encoding="utf-8"), subs), encoding="utf-8")
                notes.append(f"appended Step 0 / learnings / Maintenance sections to {st['main']}")
            else:
                notes.append(f"{st['main']} already references evergreen.json; nothing appended")
        else:
            notes.append(f"{st['main']} exists; add the Maintenance section (or rerun with --append-maintenance)")
    return notes


def new_state(name: str, topic: str, kind: str, tier: str, main: str, protocol: str, source: str | None,
              last_checked: date | None = None) -> dict:
    mn, mx, start = TIERS.get(tier, TIERS["moderate"])
    lc = last_checked or today()
    lc_dt = datetime.combine(lc, datetime.min.time())
    st = {
        "evergreen": PROTOCOL_VERSION,
        "name": name, "kind": kind, "main": main,
        "files": {"research": "RESEARCH.md", "changelog": "CHANGELOG.md", "learnings": "LEARNINGS.md"},
        "protocol": protocol, "source": source, "topic": topic,
        "tier": tier, "interval_days": start, "last_checked": fmt_when(lc_dt),
        "next_due": None, "verify_at_use": False, "volatile_claims": [], "contradiction": None, "events": [],
        "streak": {"quiet": 0, "pinned_min": 0, "pinned_max": 0, "vau_quiet": 0},
        "history": [{"date": fmt_when(lc_dt), "m": None, "interval_after": start, "note": "created"}],
        "counts": {"learnings": 0, "changes": 0, "research": 0}, "consolidate_every": 25,
    }
    if kind == "map":
        st["files"] = {"changelog": "CHANGELOG.md", "learnings": "LEARNINGS.md"}
    if kind in TESTED_KINDS:
        st["files"]["tests"] = "TESTS.md"
        st["tests"] = new_tests_block()
        st["counts"]["tests"] = 0
    if tier != "none" and start:
        st["next_due"] = fmt_when(lc_dt + timedelta(days=start))
    return st


# ---------- checks ----------

def unit_files(d: Path, st: dict) -> dict:
    files = {"main": d / st.get("main", "SKILL.md")}
    for k, v in (st.get("files") or {}).items():
        files[k] = d / v
    return files


def check_links(d: Path, st: dict) -> list[str]:
    problems = []
    files = unit_files(d, st)
    texts = {}
    for k, p in files.items():
        if not p.exists():
            problems.append(f"missing {k}: {p.name}")
            continue
        texts[k] = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
    names = {k: p.name for k, p in files.items()}
    for k, txt in texts.items():
        for other, oname in names.items():
            if other == k or other not in texts:
                continue
            if oname not in txt:
                problems.append(f"{names[k]} does not link to {oname}")
    if "main" in texts and "evergreen" not in texts["main"].lower():
        problems.append(f"{names['main']} never mentions evergreen (add the Maintenance section)")
    defined, referenced = set(), set()
    for txt in texts.values():
        defined |= set(DEF_RE.findall(txt))
        referenced |= set(ID_RE.findall(txt))
    arch_txt = ""
    for arch in d.glob("*-ARCHIVE.md"):
        arch_txt += arch.read_text(encoding="utf-8", errors="replace")
    defined |= set(DEF_RE.findall(arch_txt))
    for rid in sorted(referenced - defined):
        problems.append(f"referenced but never defined: {rid}")
    proto = st.get("protocol")
    if proto and not str(proto).startswith("$") and resolve_protocol(d, st) is None:
        problems.append(f"protocol path does not resolve: {proto}" + (" (pointer mode: register the plugin first)" if proto == "plugin" else ""))
    return problems


FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def frontmatter_problems(path: Path) -> list[str]:
    """Cowork's plugin validator rejects anything shaped like <tag> in a skill/agent description."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    m = FM_RE.match(txt)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        key = line.split(":", 1)[0].strip().lower()
        if key in ("description", "when_to_use") and re.search(r"<[^>\n]+>", line):
            out.append(f"{path.name}: {key} contains an angle-bracket placeholder (plugin validators read it as an XML tag)")
    return out


def lint(d: Path, st: dict) -> list[str]:
    notes = []
    files = unit_files(d, st)
    main = files.get("main")
    if main and main.exists():
        notes += frontmatter_problems(main)
    if st.get("kind") == "plugin":
        for p in sorted(list(d.glob("skills/*/SKILL.md")) + list(d.glob("agents/*.md"))):
            notes += [f"{p.parent.name}/{n}" if p.name == "SKILL.md" else n for n in frontmatter_problems(p)]
    if main and main.exists():
        n = len(main.read_text(encoding="utf-8", errors="replace").splitlines())
        cap = BUDGETS["codemap"] if st.get("kind") == "map" else BUDGETS["main"]
        if n > BUDGETS["main_hard"]:
            notes.append(f"{main.name}: {n} lines, over hard cap {BUDGETS['main_hard']}")
        elif n > cap:
            notes.append(f"{main.name}: {n} lines, over budget {cap} (archive or tighten)")
    lp = files.get("learnings")
    if lp and lp.exists():
        txt = strip_comments(lp.read_text(encoding="utf-8", errors="replace"))
        entries = re.split(r"^###\s+L-\d{3,}", txt, flags=re.M)[1:]
        heads = re.findall(r"^###\s+(L-\d{3,})[^\n]*", txt, flags=re.M)
        active = 0
        for head, body in zip(heads, entries):
            if re.search(r"Status:\s*(promoted|retired)", body):
                continue
            active += 1
            for field in ("Trigger", "Hypothesis", "Rule", "Evidence"):
                if not re.search(rf"^\s*-\s*{field}:", body, flags=re.M):
                    notes.append(f"{head}: missing {field}")
        if active > int(st.get("consolidate_every", 25)):
            notes.append(f"LEARNINGS.md: {active} active entries > consolidate_every; run a consolidation pass")
        if len(txt.splitlines()) > BUDGETS["learnings"]:
            notes.append(f"LEARNINGS.md: over {BUDGETS['learnings']} lines; archive retired entries")
    rp = files.get("research")
    if rp and rp.exists():
        txt = rp.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"## Current understanding(.*?)(?=^## )", txt, flags=re.S | re.M)
        if m and len(m.group(1).strip().splitlines()) > BUDGETS["understanding"]:
            notes.append(f"RESEARCH.md: Current understanding over {BUDGETS['understanding']} lines")
        if "## Search plan" not in txt:
            notes.append("RESEARCH.md: no Search plan section")
        elif st.get("tier") != "none":
            plan = re.search(r"## Search plan(.*?)(?=^## )", txt, flags=re.S | re.M)
            body = plan.group(1) if plan else ""
            # a track is a labelled block: a line that starts with its name and ends in a colon, or a heading
            missing = [t for t in SEARCH_TRACKS
                       if not re.search(rf"^\s*(?:#+\s*|\*\*)?{t}\b[^\n]*:\s*\**\s*$", body, flags=re.M | re.I)]
            if missing:
                notes.append("RESEARCH.md: Search plan is missing the "
                             + ", ".join(missing) + " track" + ("s" if len(missing) > 1 else "")
                             + " (PROTOCOL §4; see templates/RESEARCH.md.template)")
    if tests_apply(st):
        ev = d / "evals" / "evals.json"
        notes += evals_problems(ev) if ev.exists() else ["no evals/evals.json (PROTOCOL §11; run evergreen.py test-init)"]
    tp = files.get("tests")
    if tp and tp.exists():
        txt = strip_comments(tp.read_text(encoding="utf-8", errors="replace"))
        heads = re.findall(r"^###\s+(T-\d{8}-\d+)\b", txt, flags=re.M)
        for head, body in zip(heads, re.split(r"^###\s+T-\d{8}-\d+", txt, flags=re.M)[1:]):
            if not re.search(r"^\s*(?:-\s*)?led to:", body, flags=re.M | re.I):
                notes.append(f"{head}: no 'led to:' line (L-, C-, R- ids or none)")
        if len(txt.splitlines()) > BUDGETS["tests"]:
            notes.append(f"{tp.name}: over {BUDGETS['tests']} lines; archive older runs to TESTS-ARCHIVE.md")
    return notes


# ---------- packaging ----------

def plugin_version() -> str:
    try:
        return json.loads((plugin_root() / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version", "0.0.0")
    except Exception:
        return "0.0.0"


SHARE_EXCLUDE_DIRS = {"profile"}  # the owner's preferences and environment facts never travel to someone else


def share_config(text: str) -> str:
    """The recipient's copy of evergreen.config.json: no owner address, no owner store path. Their first
    `notify` then says the address is empty instead of mailing the owner from their machine."""
    try:
        cfg = json.loads(text)
    except Exception:
        return text
    n = cfg.setdefault("notify", {})
    n["to"] = ""
    n["auto"] = False
    n.pop("outbox_copy_to", None)
    cfg["home"] = {"nt": "%USERPROFILE%\\.evergreen", "posix": "~/.evergreen"}
    cfg["_note"] = ("Share copy: set notify.to to your own address and notify.auto to true if you want this plugin to email "
                    "you its own updates, and point `home` wherever you keep its store. " + str(cfg.get("_note", "")))
    return json.dumps(cfg, indent=2) + "\n"


def iter_plugin_files(share: bool = False):
    root = plugin_root()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in PACK_EXCLUDE and not (share and x in SHARE_EXCLUDE_DIRS and Path(dirpath) == root)]
        for f in filenames:
            if f.endswith(".pyc") or f in PACK_EXCLUDE or f.endswith((".zip", ".plugin", ".7z", ".rej", ".incoming", ".orig")):
                continue
            if f == "MANIFEST.json" and Path(dirpath) == root:
                continue  # shipped inside archives only; the tree's copy just identifies the install
            p = Path(dirpath) / f
            yield p, p.relative_to(root)


# Extensions Gmail refuses, even inside a zip (support.google.com/mail/answer/6590). Only the ones a plugin could plausibly carry.
MAIL_BLOCKED = {".ps1", ".bat", ".cmd", ".exe", ".js", ".jse", ".vbs", ".vbe", ".wsf", ".wsh", ".msi", ".jar", ".hta", ".scr", ".lnk", ".dll", ".com", ".cpl", ".sys", ".vb", ".xll"}


def shipped_bytes(p: Path, rel: Path, share: bool = False) -> bytes:
    """What actually goes into the archive for this file. Identical to the file on disk, except that a share
    archive ships a config with the owner's address and store removed."""
    data = p.read_bytes()
    if share and rel.as_posix() == "evergreen.config.json":
        return share_config(data.decode("utf-8", errors="replace")).encode("utf-8")
    return data


def pack_manifest(files: list, share: bool = False) -> dict:
    """Content manifest shipped inside every archive; pack_id identifies the shipped state for later merges."""
    entries = {}
    for p, rel in sorted(files, key=lambda x: str(x[1])):
        entries[rel.as_posix()] = hashlib.sha256(shipped_bytes(p, rel, share)).hexdigest()
    digest = hashlib.sha256("\n".join(f"{k} {v}" for k, v in entries.items()).encode("utf-8")).hexdigest()[:8]
    return {"name": "evergreen", "version": plugin_version(), "pack_id": f"{date.today().strftime('%Y%m%d')}-{digest}",
            "packed": datetime.now().strftime("%Y-%m-%dT%H:%M"), "files": entries}


INSTALL_PROMPT_FALLBACK = (
    "Install the Evergreen plugin {version} from the archive saved in this folder: <<< PASTE THE FOLDER PATH HERE >>>\n"
    "Unzip it, run `python evergreen/scripts/evergreen.py unmail evergreen`, put the `evergreen/` folder under a ROOT folder that has\n"
    ".claude-plugin/marketplace.json ({\"name\": \"mark-local\", \"plugins\": [{\"name\": \"evergreen\", \"source\": \"./evergreen\"}]}),\n"
    "then `claude plugin marketplace add ROOT` and `claude plugin install evergreen@mark-local --scope user`, and confirm with `claude plugin list`.\n"
)


def install_prompt(ver: str | None = None, share: bool = False) -> str:
    """The one-paste install prompt shipped in every archive and at the top of every update email. The recipient
    fills in one thing, the folder the attachments were saved to, and the agent does the rest (L-012).
    share=True names the `-share` archives and adds the one extra step a new owner needs."""
    ver = ver or plugin_version()
    try:
        author = (json.loads((plugin_root() / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("author") or {}).get("name") or "the owner"
    except Exception:
        author = "the owner"
    tpl = plugin_root() / "templates" / "INSTALL-PROMPT.txt"
    text = tpl.read_text(encoding="utf-8") if tpl.exists() else INSTALL_PROMPT_FALLBACK
    text = text.replace("{version}", ver).replace("{author}", author).replace("{tag}", "-share" if share else "")
    if share:
        text = text.replace("{marketplace}", "my-local").replace("{owner}", "me")
        text += SHARE_PROMPT_TAIL
    else:
        text = text.replace("{marketplace}", "mark-local").replace("{owner}", author)
    return text


SHARE_PROMPT_TAIL = (
    "9. This is a share copy: it has no `profile/` folder and its `evergreen.config.json` has no email address, so it mails\n"
    "   nobody. If I want it to email me its own updates later, tell me to set `notify.to` to my address and `notify.auto`\n"
    "   to true in that file; leaving them as they are is fine and everything else works.\n"
)


def split_file(path: Path, kb: int) -> list[Path]:
    """Cut `path` into `path.partNN` pieces of at most `kb` KB, for mail routes with a small per-attachment ceiling
    (a connector that carries attachments as base64 through the model, for one; L-013). The whole file stays; the
    install prompt tells the recipient to join the pieces in order. Returns the pieces (none when the file already fits)."""
    size = max(1, int(kb)) * 1024
    data = path.read_bytes()
    if len(data) <= size:
        return []
    parts = []
    for i in range(0, len(data), size):
        pp = path.with_name(f"{path.name}.part{i // size + 1:02d}")
        pp.write_bytes(data[i:i + size])
        parts.append(pp)
    return parts


def pack(out_dir: Path, mail: bool = False, git_tag: bool = True, split_kb: int = 0, after: bool = True,
         share: bool = False) -> list[Path]:
    """Write evergreen-<version>.zip (folder inside, for 7-Zip/backup) and evergreen.plugin (flat, for Cowork).
    mail=True writes evergreen-<version>-mail.zip instead: files with mail-blocked extensions are stored with
    `.txt` appended so Gmail accepts the archive; `unmail` restores the names after unzipping.
    share=True writes the `-share` form for someone else: no `profile/` (the owner's preferences and environment
    facts) and an `evergreen.config.json` with no address and `notify.auto` off, so their install never mails the
    owner. A share archive is a copy to give away, so it never becomes this install's baseline and never tags.
    Every archive carries MANIFEST.json; the shipped state becomes this install's baseline, a copy of the zip is kept
    in EVERGREEN_HOME/packs/, and when the plugin folder is a git repo the state is committed and tagged.
    Every archive also carries INSTALL-PROMPT.txt (and a copy is written beside it) so the recipient installs by pasting
    one prompt and a folder path. split_kb > 0 additionally cuts the mail zip into .partNN pieces of that size.
    after=False skips the baseline/keep/git step (used when an update email packs the current tree as an attachment)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ver = plugin_version()
    files = list(iter_plugin_files(share=share))
    if share:
        after = False
        git_tag = False
    manifest = pack_manifest(files, share=share)
    man_text = json.dumps(manifest, indent=2) + "\n"
    prompt = install_prompt(ver, share=share)
    install = (
        f"Evergreen {ver} (self-maintaining skills for AI agents)\n\n"
        "EASIEST INSTALL: open Claude Code, paste the contents of INSTALL-PROMPT.txt (inside this archive, beside it as\n"
        f"evergreen-{ver}-INSTALL-PROMPT.txt, and at the top of the update email), and replace its one placeholder with the\n"
        "folder you saved this archive to. The agent unzips, restores names, registers the local marketplace, installs,\n"
        "verifies, and runs the first audit. Manual route: evergreen/README.md > Install.\n"
        "Cowork: install the .plugin file (`python evergreen/scripts/evergreen.py pack` rebuilds it); other agents:\n"
        "`python evergreen/scripts/evergreen.py export <repo>`.\n"
    )
    tag = "-share" if share else ""
    if share:
        install += (
            "\nSHARE COPY: this archive has no `profile/` folder (the owner's preferences and environment facts) and its\n"
            "evergreen.config.json carries no email address, so nothing is mailed anywhere until you set `notify.to` to your\n"
            "own address and `notify.auto` to true. Everything else, protocol, skills, scripts, templates, is complete.\n"
        )
    prompt_path = out_dir / f"evergreen-{ver}{tag}-INSTALL-PROMPT.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    if mail:
        renamed = [str(rel) for _, rel in files if rel.suffix.lower() in MAIL_BLOCKED]
        install += (
            "\nEMAIL-SAFE FORM: Gmail rejects some script types even inside a zip, so these files are stored with `.txt`\n"
            "appended: " + ", ".join(renamed) + "\n"
            "The install prompt restores them (`python evergreen/scripts/evergreen.py unmail evergreen`); by hand, drop the `.txt`.\n"
            "Numbered .partNN files beside this archive are pieces of it: join them in order first. The .plugin file for\n"
            "Cowork is not included; `pack` rebuilds it.\n"
        )
        zpath = out_dir / f"evergreen-{ver}{tag}-mail.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("INSTALL.txt", install)
            z.writestr("INSTALL-PROMPT.txt", prompt)
            z.writestr("evergreen/MANIFEST.json", man_text)
            for p, rel in files:
                arc = str(Path("evergreen") / rel)
                if rel.suffix.lower() in MAIL_BLOCKED:
                    arc += ".txt"
                z.writestr(arc, shipped_bytes(p, rel, share))
        parts = split_file(zpath, split_kb) if split_kb else []
        if after:
            _after_pack(zpath, manifest, git_tag)
        return [zpath, prompt_path] + parts
    zpath = out_dir / f"evergreen-{ver}{tag}.zip"
    ppath = out_dir / ("evergreen-share.plugin" if share else "evergreen.plugin")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("INSTALL.txt", install)
        z.writestr("INSTALL-PROMPT.txt", prompt)
        z.writestr("evergreen/MANIFEST.json", man_text)
        for p, rel in files:
            z.writestr(str(Path("evergreen") / rel), shipped_bytes(p, rel, share))
    with zipfile.ZipFile(ppath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("MANIFEST.json", man_text)
        for p, rel in files:
            z.writestr(str(rel), shipped_bytes(p, rel, share))
    if after:
        _after_pack(zpath, manifest, git_tag)
    return [zpath, ppath, prompt_path]


def _after_pack(zpath: Path, manifest: dict, git_tag: bool) -> None:
    """Baseline the shipped state, keep the archive, commit and tag when this is a git repo. Never raises."""
    try:
        import evergreen_sync as es
        es.take_baseline(note=f"pack {manifest['version']}", pack_id=manifest["pack_id"])
        keep = evergreen_home() / "packs"
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy2(zpath, keep / f"{zpath.stem}-{manifest['pack_id']}{zpath.suffix}")
    except Exception as e:
        print(f"[evergreen] pack: baseline/keep skipped ({e})", file=sys.stderr)
    root = plugin_root()
    if git_tag and shutil.which("git") and git(["rev-parse", "--is-inside-work-tree"], root) == "true":
        if git(["status", "--porcelain"], root):
            git(["add", "-A"], root)
            git(["commit", "-q", "-m", f"pack {manifest['version']} ({manifest['pack_id']})"], root)
        tag = f"pack-{manifest['version']}-{manifest['pack_id']}"
        if git(["tag", tag], root) is not None:
            print(f"git: tagged {tag}")


def unmail(folder: Path) -> list[Path]:
    """Undo the mail-safe renames: any `<name>.<blocked-ext>.txt` becomes `<name>.<blocked-ext>`."""
    restored = []
    for p in folder.rglob("*.txt"):
        inner = Path(p.stem)  # strips the trailing .txt
        if inner.suffix.lower() in MAIL_BLOCKED:
            target = p.with_name(p.stem)
            if not target.exists():
                p.rename(target)
                restored.append(target)
    return restored


def export(repo: Path) -> Path:
    """Copy the plugin into <repo>/.agents/ keeping its layout, so skills' ../../ links keep resolving."""
    dest = repo / ".agents"
    dest.mkdir(parents=True, exist_ok=True)
    for p, rel in iter_plugin_files():
        if rel.parts and rel.parts[0] in ("hooks", ".claude-plugin"):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    return dest


# ---------- commands ----------

def cmd_home(a):
    print(evergreen_home())


def cmd_status(a):
    d, st = load_state(a.unit)
    fr = freshness(st)
    fr["flags"] += test_flags(st)
    line = status_line(d, st, fr, verbose=True)
    if st.get("kind") == "map":
        dr = drift(st)
        if dr["commits"] is not None:
            line += f" drift {dr['commits']} commits / {dr['files_pct']}% files" + (" STALE" if dr["stale"] else "")
        elif dr["note"]:
            line += f" drift: {dr['note']}"
    print(line)


def cmd_audit(a):
    roots = [Path(r) for r in a.roots] if a.roots else default_roots()
    units = discover(roots)
    rows, stale, problems, failing = [], 0, 0, 0
    for d in sorted(units, key=lambda p: str(p).lower()):
        try:
            _, st = load_state(d)
        except Exception as e:
            rows.append({"path": str(d), "error": str(e)})
            continue
        fr = freshness(st)
        fr["flags"] += test_flags(st)
        row = {"path": str(d), **fr, "source_state": source_state(d, st), "tests": st.get("tests")}
        if st.get("kind") == "map":
            dr = drift(st)
            row["drift"] = dr
            if dr.get("stale"):
                fr["status"] = "STALE"
                fr["flags"].append(f"drift {dr['commits']}c/{dr['files_pct']}%")
                row["status"] = "STALE"
        if a.checks:
            probs = check_links(d, st) + lint(d, st)
            row["problems"] = probs
            problems += len(probs)
        if fr["status"] == "STALE":
            stale += 1
        if (st.get("tests") or {}).get("failing"):
            failing += 1
        rows.append(row)
        if a.json:
            continue
        if a.brief:  # the session-start line only carries what needs a decision now; untested and overdue wait for an audit
            fr["flags"] = [f for f in fr["flags"] if f not in ("untested", "tests-overdue")]
        if a.brief and fr["status"] != "STALE" and not fr["flags"]:
            continue
        line = status_line(d, st, fr, verbose=a.checks)
        if a.brief:
            line = "[evergreen] " + line
        print(line)
        if a.checks:
            for p in row.get("problems", []):
                print(f"    - {p}")
    if a.json:
        print(json.dumps({"home": str(evergreen_home()), "stale": stale, "units": rows}, indent=2))
        return
    if a.brief:
        if stale:
            print(f"[evergreen] {stale} unit(s) due for refresh. Do the user's task first, then run evergreen-refresh in this session.")
        return
    print(f"-- {len(units)} unit(s), {stale} stale" + (f", {problems} problem(s)" if a.checks else "")
          + (f", {failing} with failing tests" if failing else "") + f", home {evergreen_home()}")
    if not units:
        print("   (no units found; run `evergreen.py register <unit>` or `init`)")
    if a.strict and (stale or problems):
        sys.exit(1)


def cmd_next(a):
    d, st = load_state(a.unit)
    new = compute_next(st, a.m, datetime.now(), contradiction=a.contradiction, use_time=a.use_time, jitter=False)
    print(f"interval {fmt_days(st.get('interval_days'))} -> {fmt_days(new.get('interval_days'))}, next_due {new.get('next_due')}, tier {new.get('tier')} | {new.get('report')}")


def cmd_checked(a):
    d, st = load_state(a.unit)
    new = compute_next(st, a.m, datetime.now(), contradiction=a.contradiction, use_time=a.use_time, jitter=not a.no_jitter)
    if a.note:
        new["history"][-1]["note"] = a.note
    new.setdefault("counts", {}).setdefault("research", 0)
    if a.m is not None and not a.use_time:
        new["counts"]["research"] = new["counts"].get("research", 0) + 1
    rep = new.pop("report", "")
    save_state(d, new)
    register(d, new)
    print(f"{new['name']}: interval {fmt_days(st.get('interval_days'))} -> {fmt_days(new.get('interval_days'))}, next_due {new.get('next_due')}, tier {new.get('tier')} | {rep}")
    maybe_notify(d, new, a)


EVENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?):(.*?)(?::(\d+(?:\.\d+)?))?$")


def cmd_flag(a):
    d, st = load_state(a.unit)
    if a.contradiction:
        st["contradiction"] = {"date": fmt_when(datetime.now()), "note": a.contradiction}
        print(f"{st['name']}: contradiction flagged; next use triggers a refresh at min interval")
    if a.clear_contradiction:
        st["contradiction"] = None
        print(f"{st['name']}: contradiction cleared")
    for ev in a.event or []:
        m = EVENT_RE.match(ev)
        if not m:
            print(f"bad --event {ev}; use DATE:label[:settle_days]")
            continue
        e = {"date": m.group(1), "label": m.group(2).strip().strip('"\''), "settle_days": float(m.group(3)) if m.group(3) else 2}
        st.setdefault("events", []).append(e)
        ed = parse_when(e["date"])
        due = parse_when(st.get("next_due"))
        if ed and due and ed + timedelta(days=e["settle_days"]) < due:
            st["next_due"] = fmt_when(ed + timedelta(days=e["settle_days"]))
        print(f"{st['name']}: event added {e['date']} '{e['label']}', next_due now {st.get('next_due')}")
    if a.clear_failing is not None:
        t = st.get("tests")
        if not isinstance(t, dict):
            print(f"{st['name']}: no tests block (run evergreen.py test-init)")
        elif a.clear_failing:
            t["failing"] = [x for x in t.get("failing") or [] if x not in set(a.clear_failing)]
            print(f"{st['name']}: cleared {', '.join(a.clear_failing)}; failing now [{', '.join(t['failing'])}]")
        else:
            t["failing"] = []
            print(f"{st['name']}: failing list cleared")
    save_state(d, st)


def cmd_init(a):
    d = Path(a.dir).expanduser()
    tier = a.tier
    if tier not in TIERS:
        print(f"unknown tier {tier}; one of {', '.join(TIERS)}")
        return
    if a.pointer:
        protocol = "plugin"
    else:
        protocol = "MAINTENANCE.md" if a.standalone else (a.protocol or "../../protocol/PROTOCOL.md")
    lc = None
    if a.last_checked:
        p = parse_when(a.last_checked)
        lc = p.date() if p else None
    if (d / "evergreen.json").exists() and not a.force:
        print(f"{d} already has evergreen.json (use --force to overwrite state)")
        _, st = load_state(d)
    else:
        st = new_state(a.name, a.topic, a.kind, tier, a.main, protocol, a.source, lc)
        d.mkdir(parents=True, exist_ok=True)
        save_state(d, st)
    notes = scaffold(d, st, a.standalone, a.append_maintenance, a.kind, pointer=a.pointer)
    register(d, st)
    print(f"initialized {st['name']} ({st['kind']}, tier {st['tier']}, next_due {st.get('next_due')}) in {d}")
    for n in notes:
        print("  - " + n)


def cmd_test_init(a):
    """Give an existing skill or plugin the testing layer: files.tests, the tests block, TESTS.md, evals/evals.json. Idempotent."""
    d, st = load_state(a.unit)
    if not tests_apply(st):
        print(f"{st['name']}: kind {st.get('kind')} carries no test suite (skills and plugins only)")
        return
    notes = []
    files = st.setdefault("files", {})
    if "tests" not in files:
        files["tests"] = "TESTS.md"
        notes.append("added files.tests to evergreen.json")
    if not isinstance(st.get("tests"), dict):
        st["tests"] = new_tests_block()
        notes.append("added tests block to evergreen.json")
    st.setdefault("counts", {}).setdefault("tests", 0)
    notes += write_templates(d, TEST_FILES, scaffold_subs(st, str(st.get("kind"))))
    save_state(d, st)
    print(f"{st['name']}: testing layer ready (write the cases in evals/evals.json, then run evergreen-test)")
    for n in notes:
        print("  - " + n)


def cmd_tested(a):
    d, st = load_state(a.unit)
    if not tests_apply(st):
        print(f"{st['name']}: kind {st.get('kind')} carries no test suite (skills and plugins only)")
        return
    t = st.setdefault("tests", new_tests_block())
    now = datetime.now()
    passed, failed = int(a.passed or 0), int(a.failed or 0)
    failing = [x.strip() for x in (a.failing or "").split(",") if x.strip()] if failed else []
    t.update({"last_run": fmt_when(now, True), "harness": a.harness or t.get("harness"), "env": a.env or env_default(),
              "cases": passed + failed, "passed": passed, "failed": failed, "failing": failing})
    if failed:
        t["last_failure"] = {"date": fmt_when(now), "note": a.note}
    c = st.setdefault("counts", {})
    c["tests"] = c.get("tests", 0) + 1
    save_state(d, st)
    print(f"{st['name']}: tests {passed}/{passed + failed} passed, failing [{', '.join(failing)}]; next entry {next_entry_id(d, st)}")
    maybe_notify(d, st, a)


def cmd_failed(a):
    """A failure seen in use (not a suite run): remember the case, then say whether to research first or tune directly."""
    d, st = load_state(a.unit)
    if not tests_apply(st):
        print(f"{st['name']}: kind {st.get('kind')} carries no test suite (skills and plugins only)")
        return
    t = st.setdefault("tests", new_tests_block())
    now = datetime.now()
    if a.case not in (t.get("failing") or []):
        t.setdefault("failing", []).append(a.case)
    t["last_failure"] = {"date": fmt_when(now), "case": a.case, "class": a.cls, "note": a.note}
    save_state(d, st)
    print(f"{st['name']}: failure recorded, {a.case} ({a.cls}); failing now [{', '.join(t['failing'])}]")
    print(research_verdict(st, a.cls, now))
    print(f"next entry {next_entry_id(d, st)}")


def cmd_use_log(a):
    """PostToolUse hook body: one JSON line per Skill invocation. Silent and exception-free by design, since some hook
    events feed stdout back into the model's context."""
    try:
        raw = Path(a.file).expanduser().read_text(encoding="utf-8") if a.file else sys.stdin.read()
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict) or str(payload.get("tool_name") or "") != "Skill":
            return
        ti = payload.get("tool_input") or {}
        name = ""
        if isinstance(ti, dict):
            name = next((str(ti[k]) for k in ("skill", "name", "command", "skill_name") if ti.get(k)), "")
        elif isinstance(ti, str):
            name = ti
        name = name.strip().lstrip("/").split()[0] if name.strip() else ""
        if not name:
            return
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "skill": name, "session_id": payload.get("session_id"),
               "transcript_path": payload.get("transcript_path"), "cwd": payload.get("cwd"), "env": env_default()}
        p = uses_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_uses(skill: str | None = None, days: int = 7) -> list[dict]:
    """Recorded skill uses, newest first, within the last `days` days (0 = all) and for one skill when given."""
    p = uses_path()
    if not p.exists():
        return []
    rows = []
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds") if days and days > 0 else ""
    for i, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if isinstance(r, dict) and str(r.get("ts") or "") >= since and (not skill or r.get("skill") == skill):
            rows.append((str(r.get("ts") or ""), i, r))
    rows.sort(key=lambda x: x[:2], reverse=True)  # newest first; same second: the later line
    return [r for _, _, r in rows]


def cmd_uses(a):
    rows = read_uses(a.skill, a.days)
    shown = rows[:a.limit] if a.limit and a.limit > 0 else rows
    if a.json:
        print(json.dumps({"file": str(uses_path()), "count": len(rows), "uses": shown}, indent=2))
        return
    for r in shown:
        print(f"{str(r.get('ts') or '')[:16]} {str(r.get('skill') or ''):<24} session {str(r.get('session_id') or '')[:8]:<8}  "
              f"transcript {r.get('transcript_path') or '-'}  cwd {r.get('cwd') or '-'}")
    print(f"-- {len(rows)} use(s)" + (f" of {a.skill}" if a.skill else "") + (f" in the last {a.days} day(s)" if a.days and a.days > 0 else "")
          + f", {uses_path()}")


def cmd_map_slug(a):
    print(map_slug(Path(a.repo)))


def cmd_map_init(a):
    repo = Path(a.repo).expanduser().resolve()
    slug = map_slug(repo)
    d = evergreen_home() / "maps" / slug
    name = a.name or slug
    if (d / "evergreen.json").exists():
        _, st = load_state(d)
        print(f"map exists: {d}")
    else:
        st = new_state(name, f"codemap of {repo}", "map", "code", "CODEMAP.md",
                       a.protocol or str((plugin_root() / "protocol" / "PROTOCOL.md").resolve()), None)
        st["repo"] = {"root": str(repo), "sha": git(["rev-parse", "HEAD"], repo), "remote": git(["config", "--get", "remote.origin.url"], repo),
                      "drift": {"commits": 30, "files_pct": 20}, "export_to_repo": False}
        d.mkdir(parents=True, exist_ok=True)
        save_state(d, st)
    notes = scaffold(d, st, False, False, "map")
    register(d, st)
    print(f"codemap unit {name} at {d} (sha {(st.get('repo') or {}).get('sha')})")
    for n in notes:
        print("  - " + n)


def cmd_drift(a):
    d, st = load_state(a.unit)
    dr = drift(st)
    print(json.dumps(dr))
    if a.update_sha and (st.get("repo") or {}).get("root"):
        sha = git(["rev-parse", "HEAD"], Path(st["repo"]["root"]))
        if sha:
            st["repo"]["sha"] = sha
            save_state(d, st)
            print(f"sha updated to {sha}")


def cmd_links(a):
    d, st = load_state(a.unit)
    probs = check_links(d, st)
    if not probs:
        print(f"{st['name']}: links OK")
    for p in probs:
        print(f"  - {p}")
    if probs and a.strict:
        sys.exit(1)


def cmd_lint(a):
    d, st = load_state(a.unit)
    notes = check_links(d, st) + lint(d, st)
    if not notes:
        print(f"{st['name']}: lint OK")
    for n in notes:
        print(f"  - {n}")
    if notes and a.strict:
        sys.exit(1)


def cmd_register(a):
    d, st = load_state(a.unit)
    register(d, st)
    print(f"registered {st['name']} -> {registry_path()}")


def cmd_unregister(a):
    d = unit_dir(a.unit)
    unregister(d)
    print(f"unregistered {d}")


def cmd_bump(a):
    d, st = load_state(a.unit)
    c = st.setdefault("counts", {"learnings": 0, "changes": 0, "research": 0})
    for k in ("learnings", "changes", "research", "tests"):
        if getattr(a, k):
            c[k] = c.get(k, 0) + 1
    save_state(d, st)
    print(f"{st['name']}: counts {c}")
    maybe_notify(d, st, a)


def cmd_export(a):
    dest = export(Path(a.repo).expanduser())
    print(f"exported plugin to {dest} (skills at {dest / 'skills'}). Now paste templates/AGENTS.md.snippet into {Path(a.repo) / 'AGENTS.md'}.")


def cmd_pack(a):
    out = Path(a.out).expanduser() if a.out else plugin_root().parent
    share = getattr(a, "share", False)
    for p in pack(out, mail=a.mail, git_tag=not a.no_git, split_kb=a.split or 0, share=share):
        tag = ""
        if "-share" in p.name and p.suffix in (".zip", ".plugin"):
            tag = "  [share copy: no profile/, no notify address]"
        elif p.suffix == ".zip" and a.mail:
            tag = "  [email-safe: scripts stored as .txt]"
        elif p.name.endswith("-INSTALL-PROMPT.txt"):
            tag = "  [paste into Claude Code with the folder path; also inside the archive]"
        elif ".part" in p.suffix:
            tag = "  [piece; the recipient joins them in order]"
        print(f"wrote {p} ({p.stat().st_size // 1024} KB){tag}")


def is_plugin_unit(d: Path, st: dict) -> bool:
    if st.get("kind") == "plugin":
        return True
    try:
        return d.resolve() == plugin_root().resolve()
    except Exception:
        return False


def maybe_notify(d: Path, st: dict, a) -> None:
    """After a recorded check or a bump on the plugin itself: publish the self-update (git push or PR with
    update.transport git, the update email otherwise) when the transport's auto flag is on.
    Synchronous (the caller is an agent's shell command, not a hook); `--no-notify` skips it."""
    if getattr(a, "no_notify", False) or not is_plugin_unit(d, st):
        return
    try:
        import evergreen_sync as es
        if es.update_transport() == "git":
            if not es.git_config().get("auto", True):
                return
        else:
            cfg = es.notify_config()
            if not cfg.get("auto") or not cfg.get("to"):
                return
        msg = es.notify(if_changed=True)
        if msg:
            print(f"[notify] {msg}")
    except Exception as e:
        print(f"[notify] skipped: {e}", file=sys.stderr)


def cmd_unmail(a):
    restored = unmail(Path(a.folder).expanduser())
    for p in restored:
        print(f"restored {p}")
    print(f"{len(restored)} file(s) restored" if restored else "nothing to restore (no *.ext.txt files from a mail-safe archive)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="evergreen.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--strict", action="store_true", help="exit non-zero on problems or stale units")
    p.add_argument("--strict", dest="strict_top", action="store_true", help="same as the per-command --strict")
    sp = p.add_subparsers(dest="cmd")

    sp.add_parser("home", parents=[common]).set_defaults(fn=cmd_home)
    s = sp.add_parser("status", parents=[common]); s.add_argument("unit"); s.set_defaults(fn=cmd_status)
    s = sp.add_parser("audit", parents=[common]); s.add_argument("--brief", action="store_true"); s.add_argument("--json", action="store_true")
    s.add_argument("--checks", action="store_true", help="also run links + lint per unit"); s.add_argument("--roots", nargs="*"); s.set_defaults(fn=cmd_audit)
    for name, fn in (("next", cmd_next), ("checked", cmd_checked)):
        s = sp.add_parser(name, parents=[common]); s.add_argument("unit"); s.add_argument("--m", type=float, default=None, help="change magnitude 0..1; omit for a failed refresh")
        s.add_argument("--note"); s.add_argument("--contradiction", action="store_true"); s.add_argument("--use-time", action="store_true")
        s.add_argument("--no-jitter", action="store_true"); s.add_argument("--no-notify", action="store_true", help="do not publish (git push / PR, or the update email) afterwards")
        s.set_defaults(fn=fn)
    s = sp.add_parser("flag", parents=[common]); s.add_argument("unit"); s.add_argument("--contradiction"); s.add_argument("--clear-contradiction", action="store_true")
    s.add_argument("--event", action="append"); s.add_argument("--clear-failing", nargs="*", metavar="ID", help="drop these case ids from tests.failing (none given: clear the list)")
    s.set_defaults(fn=cmd_flag)
    s = sp.add_parser("init", parents=[common]); s.add_argument("dir"); s.add_argument("--name", required=True); s.add_argument("--topic", default="")
    s.add_argument("--kind", default="skill", choices=["skill", "doc", "profile", "plugin"]); s.add_argument("--tier", default="moderate")
    s.add_argument("--main", default="SKILL.md"); s.add_argument("--protocol"); s.add_argument("--standalone", action="store_true")
    s.add_argument("--append-maintenance", action="store_true"); s.add_argument("--source"); s.add_argument("--last-checked")
    s.add_argument("--pointer", action="store_true", help="protocol 'plugin': MAINTENANCE.md points at the installed plugin instead of copying it")
    s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_init)
    s = sp.add_parser("test-init", parents=[common], help="add TESTS.md, evals/evals.json and the tests block to an existing skill or plugin"); s.add_argument("unit"); s.set_defaults(fn=cmd_test_init)
    s = sp.add_parser("tested", parents=[common], help="record a suite run"); s.add_argument("unit"); s.add_argument("--passed", type=int, default=0); s.add_argument("--failed", type=int, default=0)
    s.add_argument("--failing", help="comma-separated ids of the failing cases"); s.add_argument("--harness"); s.add_argument("--env", help="default: EVERGREEN_ENV, else the hostname")
    s.add_argument("--note"); s.add_argument("--no-notify", action="store_true", help="do not publish (git push / PR, or the update email) afterwards"); s.set_defaults(fn=cmd_tested)
    s = sp.add_parser("failed", parents=[common], help="record a failure seen in use and decide research-first or tune"); s.add_argument("unit"); s.add_argument("--case", required=True)
    s.add_argument("--class", dest="cls", required=True, choices=FAILURE_CLASSES); s.add_argument("--note"); s.set_defaults(fn=cmd_failed)
    s = sp.add_parser("use-log", parents=[common], help="PostToolUse hook body: log a Skill use from the JSON payload on stdin"); s.add_argument("--file", help="read the payload from a file instead of stdin"); s.set_defaults(fn=cmd_use_log)
    s = sp.add_parser("uses", parents=[common], help="recent skill uses from EVERGREEN_HOME/uses.jsonl, newest first"); s.add_argument("--skill"); s.add_argument("--days", type=int, default=7)
    s.add_argument("--limit", type=int, default=20); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_uses)
    s = sp.add_parser("map-slug", parents=[common]); s.add_argument("repo"); s.set_defaults(fn=cmd_map_slug)
    s = sp.add_parser("map-init", parents=[common]); s.add_argument("repo"); s.add_argument("--name"); s.add_argument("--protocol"); s.set_defaults(fn=cmd_map_init)
    s = sp.add_parser("drift", parents=[common]); s.add_argument("unit"); s.add_argument("--update-sha", action="store_true"); s.set_defaults(fn=cmd_drift)
    s = sp.add_parser("links", parents=[common]); s.add_argument("unit"); s.set_defaults(fn=cmd_links)
    s = sp.add_parser("lint", parents=[common]); s.add_argument("unit"); s.set_defaults(fn=cmd_lint)
    s = sp.add_parser("register", parents=[common]); s.add_argument("unit"); s.set_defaults(fn=cmd_register)
    s = sp.add_parser("unregister", parents=[common]); s.add_argument("unit"); s.set_defaults(fn=cmd_unregister)
    s = sp.add_parser("bump", parents=[common]); s.add_argument("unit"); s.add_argument("--learnings", action="store_true")
    s.add_argument("--changes", action="store_true"); s.add_argument("--research", action="store_true"); s.add_argument("--tests", action="store_true")
    s.add_argument("--no-notify", action="store_true"); s.set_defaults(fn=cmd_bump)
    s = sp.add_parser("export", parents=[common]); s.add_argument("repo"); s.set_defaults(fn=cmd_export)
    s = sp.add_parser("pack", parents=[common]); s.add_argument("--out"); s.add_argument("--mail", action="store_true", help="email-safe zip: blocked script types stored as .txt"); s.add_argument("--split", type=int, metavar="KB", help="also cut the mail zip into .partNN pieces of KB kilobytes (mail routes with small attachment limits)")
    s.add_argument("--no-git", action="store_true", help="do not commit and tag the packed state")
    s.add_argument("--share", action="store_true", help="copy for someone else: no profile/, no email address in the config, no baseline or tag")
    s.set_defaults(fn=cmd_pack)
    s = sp.add_parser("unmail", parents=[common]); s.add_argument("folder"); s.set_defaults(fn=cmd_unmail)
    try:
        import evergreen_sync as es
        es.add_parsers(sp, common)  # where, baseline, diff, notify, merge
    except Exception as e:  # the sync module is optional; the core keeps working without it
        print(f"[evergreen] sync commands unavailable: {e}", file=sys.stderr)

    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 0
    a.strict = bool(getattr(a, "strict", False) or getattr(a, "strict_top", False))
    try:
        a.fn(a)
    except SystemExit:
        raise
    except Exception as e:  # fail soft: hooks must never break a session
        print(f"[evergreen] {a.cmd} failed: {e}", file=sys.stderr)
        if a.strict:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
