#!/usr/bin/env python3
"""bench_intervals.py - a deterministic benchmark of the refresh schedule in protocol/INTERVALS.md.

It imports the real interval and tier logic from evergreen.py (new_state, compute_next, parse_when; nothing is
reimplemented) and runs it on synthetic units whose facts change as a Poisson process, next to four other schedules:

  evergreen   the rule itself: the tier the INTERVALS.md rubric would pick for the unit's class, starting at that
              tier's default interval, inside its bounds, with migration, verify-at-use and jitter as shipped
  matched     a fixed interval that spends the same number of checks per unit as the rule did (crawler theory:
              under a fixed budget, uniform revisits are hard to beat); it knows that count only in hindsight
  tier-start  a fixed interval at the tier's start value (live 1, fast 14, moderate 30, slow 120, glacial 365 days):
              the rule with its adaptation switched off
  fixed-14    one check every 14 days, whatever the unit
  freshcache  a constant interval per class set to FreshCache's staleness half-life for that class (arXiv 2607.04281:
              timeless 22 days, slow 16 days, medium 15 hours, fast 3 hours)
  oracle      a check at the instant of every change: zero delay, one check per change (the lower bound)

A check observes the largest magnitude of the changes since the previous check (0 when nothing changed), which is
the `m` the rule receives. Magnitudes follow a stated mix: 60% minor (0.1 to 0.29), 30% real (0.3 to 0.59),
10% major (0.6 to 0.9). A verify-at-use unit is checked at each use, one use every `--use-every` days. The change
model is synthetic: real topics are burstier and their changes are not independent, so read the numbers as a
comparison between schedules, not as a forecast for any unit.

Usage: python scripts/bench_intervals.py [--seed N] [--days 730] [--units 25] [--use-every 1] [--json]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evergreen as eg  # noqa: E402  (the rule under test; never copied here)

EPOCH = datetime(2026, 1, 5)
MIX = ((0.6, 0.10, 0.29), (0.3, 0.30, 0.59), (0.1, 0.60, 0.90))  # (share, low, high) of change magnitudes
MATERIAL = 0.3
FRESHCACHE = {"timeless": 22.0, "slow": 16.0, "medium": 15 / 24, "fast": 3 / 24}  # half-lives in days
# name, mean gap between changes in days, the tier a user would pick with the INTERVALS.md rubric, the FreshCache
# class. The first seven are plain Poisson processes, the worst case for a rule that reacts to what it saw, since
# the past predicts nothing. Two extra regimes test the claims the rule is built on: `shift` alternates 7-day and
# 120-day gaps every 180 days ("fast, then slow, then fast again"), and `burst` clusters changes like releases
# (an episode every 60 days on average, 3 changes per episode on average, spread over a few days).
CLASSES = (
    ("2d", 2, "live", "fast"),
    ("7d", 7, "fast", "medium"),
    ("14d", 14, "fast", "medium"),
    ("30d", 30, "moderate", "slow"),
    ("60d", 60, "moderate", "slow"),
    ("120d", 120, "slow", "timeless"),
    ("365d", 365, "glacial", "timeless"),
    ("shift", (7, 120, 180), "moderate", "slow"),
    ("burst", ("burst", 60, 3, 2), "moderate", "slow"),  # episode gap, changes per episode, days of spread
)
POLICIES = ("evergreen", "matched", "tier-start", "fixed-14", "freshcache", "oracle")


def gap_at(gap, t: float) -> float:
    if isinstance(gap, tuple):
        a, b, period = gap
        return a if int(t // period) % 2 == 0 else b
    return float(gap)


def magnitude(rng: random.Random) -> float:
    u, acc = rng.random(), 0.0
    for share, lo, hi in MIX:
        acc += share
        if u <= acc:
            break
    return round(rng.uniform(lo, hi), 2)


def make_changes(rng: random.Random, gap, days: float) -> list[tuple[float, float]]:
    """(time, magnitude) pairs: a Poisson process (thinned, so a time-varying gap is exact), or release-like bursts."""
    if isinstance(gap, tuple) and gap[0] == "burst":
        _, every, per, spread = gap
        out, t = [], 0.0
        while True:
            t += rng.expovariate(1.0 / every)
            if t >= days:
                return sorted(x for x in out if x[0] < days)
            n = 1
            while rng.random() > 1.0 / per:  # geometric, mean `per`
                n += 1
            out += [(t + rng.expovariate(1.0 / spread) * (k > 0), magnitude(rng)) for k in range(n)]
    top = 1.0 / min(gap[:2]) if isinstance(gap, tuple) else 1.0 / float(gap)
    out, t = [], 0.0
    while True:
        t += rng.expovariate(top)
        if t >= days:
            return out
        if rng.random() * top <= 1.0 / gap_at(gap, t):
            out.append((t, magnitude(rng)))


def days_since_epoch(when: str | None) -> float | None:
    dt = eg.parse_when(when)
    return None if dt is None else (dt - EPOCH).total_seconds() / 86400


def evergreen_checks(changes: list[tuple[float, float]], tier: str, days: float, use_every: float) -> list[float]:
    """Check times the shipped rule produces, run until the first check at or after the horizon."""
    st = eg.new_state("bench", "synthetic", "skill", tier, "SKILL.md", "plugin", None, EPOCH.date())
    t, last, i, checks = days_since_epoch(st["next_due"]), 0.0, 0, []
    while True:
        m = 0.0
        while i < len(changes) and changes[i][0] <= t:
            if changes[i][0] > last:
                m = max(m, changes[i][1])
            i += 1
        use_time = bool(st.get("verify_at_use"))
        st = eg.compute_next(st, m, EPOCH + timedelta(days=t), use_time=use_time, jitter=True)
        st.pop("report", None)
        st["history"] = st["history"][-2:]  # compute_next never reads history; keep the copies small
        checks.append(t)
        if t >= days:
            return checks
        last = t
        nxt = t + use_every if st.get("verify_at_use") else days_since_epoch(st.get("next_due"))
        t = max(nxt if nxt is not None else t + use_every, t + 1e-6)


def grid(interval: float, days: float, phase: float = 1.0) -> list[float]:
    out, k = [], 1
    while True:
        t = (k - 1 + phase) * interval
        out.append(t)
        if t >= days:
            return out
        k += 1


def score(changes: list[tuple[float, float]], checks: list[float], days: float) -> dict:
    """Detection delay of every change (first check at or after it), stale time for material changes, checks in range."""
    delays, material, spans, j = [], [], [], 0
    for c, mag in changes:
        while j < len(checks) and checks[j] < c:
            j += 1
        seen = checks[j] if j < len(checks) else days
        delays.append(seen - c)
        if mag >= MATERIAL:
            material.append(seen - c)
            spans.append((c, min(seen, days)))
    stale, end = 0.0, 0.0
    for a, b in sorted(spans):  # union of the intervals during which a material change was not yet seen
        a = max(a, end)
        if b > a:
            stale += b - a
            end = b
    return {"delays": delays, "material": material, "stale": stale / days, "checks": sum(1 for t in checks if t < days)}


def run(seed: int = 1, days: float = 730, units: int = 25, use_every: float = 1.0) -> dict:
    random.seed(seed)  # the rule's own jitter draws from the module-level generator; seeding it makes runs repeatable
    per_class, years = [], days / 365.0
    for name, gap, tier, fc in CLASSES:
        acc = {p: {"delays": [], "material": [], "stale": [], "checks": []} for p in POLICIES}
        for u in range(units):
            changes = make_changes(random.Random(f"{seed}-{name}-{u}"), gap, days)
            ev = evergreen_checks(changes, tier, days, use_every)
            budget = sum(1 for t in ev if t < days)
            schedules = {
                "evergreen": ev,
                "matched": grid(days / budget, days, phase=0.5) if budget else [float(days)],
                "tier-start": grid(float(eg.TIERS[tier][2]), days),
                "fixed-14": grid(14.0, days),
                "freshcache": grid(FRESHCACHE[fc], days),
                "oracle": [c for c, _ in changes] + [days],
            }
            for p, checks in schedules.items():
                s = score(changes, checks, days)
                acc[p]["delays"] += s["delays"]
                acc[p]["material"] += s["material"]
                acc[p]["stale"].append(s["stale"])
                acc[p]["checks"].append(s["checks"] / years)
        row = {"class": name, "gap": list(gap) if isinstance(gap, tuple) else gap, "tier": tier, "freshcache": fc,
               "changes_per_unit": len(acc["oracle"]["delays"]) / units, "policies": {}}
        for p in POLICIES:
            a = acc[p]
            row["policies"][p] = {"checks_per_year": _mean(a["checks"]), "delay_all": _mean(a["delays"]),
                                  "delay_material": _mean(a["material"]), "stale_share": _mean(a["stale"])}
        per_class.append(row)
    summary = {p: {k: _mean([r["policies"][p][k] for r in per_class if r["policies"][p][k] is not None])
                   for k in ("checks_per_year", "delay_all", "delay_material", "stale_share")} for p in POLICIES}
    return {"seed": seed, "days": days, "units_per_class": units, "use_every": use_every,
            "mix": [list(x) for x in MIX], "classes": per_class, "summary": summary}


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _f(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def render(res: dict) -> str:
    lines = [f"Refresh-schedule benchmark: seed {res['seed']}, {res['days']:g} days, {res['units_per_class']} synthetic units "
             f"per class, {len(res['classes'])} classes, one use every {res['use_every']:g} day(s). Synthetic change model; "
             "means are per class, then averaged over classes.", "",
             "| Policy | Checks per year | Mean delay, all changes (days) | Mean delay, material changes (days) | Share of time holding a stale material claim |",
             "|---|---|---|---|---|"]
    for p in POLICIES:
        s = res["summary"][p]
        lines.append(f"| {p} | {_f(s['checks_per_year'])} | {_f(s['delay_all'])} | {_f(s['delay_material'])} | {_f(100 * s['stale_share'])}% |")
    lines += ["", "Per class: mean delay for material changes in days / checks per year.", "",
              "| Class (tier) | " + " | ".join(POLICIES) + " |", "|---|" + "---|" * len(POLICIES)]
    for r in res["classes"]:
        cells = [f"{_f(r['policies'][p]['delay_material'])} / {_f(r['policies'][p]['checks_per_year'], 0)}" for p in POLICIES]
        lines.append(f"| {r['class']} ({r['tier']}) | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench_intervals.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--days", type=float, default=730)
    ap.add_argument("--units", type=int, default=25, help="synthetic units per class (default 25)")
    ap.add_argument("--use-every", type=float, default=1.0, help="days between uses of a verify-at-use unit (default 1)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    res = run(a.seed, a.days, max(1, a.units), a.use_every)
    print(json.dumps(res, indent=2) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
