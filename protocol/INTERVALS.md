# Refresh Intervals

Part of the [Evergreen Protocol](PROTOCOL.md). Decides how often a unit re-researches its topic. The schedule adapts: it shortens sharply when a check finds real change, lengthens slowly when nothing changed, and stays inside bounds set by the topic's volatility tier. Topics can go fast, then slow, then fast again; the tier migration rules handle that. Evidence: [../RESEARCH.md](../RESEARCH.md) R-20260901-2.

## Tiers

Tiers set bounds and a starting interval, not the schedule. The algorithm runs inside them.

| Tier | Min | Max | Start | Character | Examples |
|---|---|---|---|---|---|
| `live` | 6 hours | 3 days | 1 day | Worthless if stale; usually `verify_at_use` instead | model availability and pricing, CVEs in a dependency, in-window events |
| `fast` | 3 days | 21 days | 14 days | Active competitive churn | AI agent tooling and conventions, MCP and skills specs, this plugin, platform policy changes, active product changelogs |
| `moderate` | 14 days | 90 days | 30 days | Real movement, slow enough to batch | mature libraries and languages, cloud service features, clinical guidelines, appraisal methodology, consumer hardware lines |
| `slow` | 60 days | 365 days | 120 days | Annual rhythm | standards and RFCs, frameworks in maintenance, tax thresholds, org policy, established engineering practice |
| `glacial` | 270 days | 900 days | 365 days | Review catches paradigm shifts and link rot | settled science, historical fact, foundational algorithms |
| `none` | | | | No web research. Learnings-driven only | personal preferences, project-specific facts, private procedures |
| `code` | 7 days | 90 days | 30 days | Codemaps: due on calendar OR drift | any repo map; drift = commits or files changed since the stamped sha |

Choosing a tier: ask "if this were wrong for a month, how bad?" and "how often did the primary source change in the last year?" Unsure: `moderate`. Bounds can be overridden per unit in `evergreen.json` when a topic is unusual.

## Change magnitude rubric (m)

Score each check on the claims the unit actually makes, not on how much the web changed in general.

| m | Meaning |
|---|---|
| 0 | Nothing affecting the unit's claims |
| 0.1 to 0.29 | Minor: new examples, version bumps, links moved, wording, a nice-to-know |
| 0.3 to 0.59 | A recommendation, step, or default changed; something added or retired |
| 0.6 to 1.0 | A core claim is now wrong, a tool or approach is deprecated or superseded, a new standard replaced the old |

`m` for the check is the largest single finding. Record it in `history` even when 0; the history is what tier migration reads.

## The hand rule (no shell needed)

Given the current `interval_days` I and the check's magnitude m:

1. `contradiction` set (a learning proved a claim wrong): I = min bound.
2. m ≥ 0.6: I = I ÷ 4. If that lands below the tier's min and the tier is `moderate` or slower, promote one tier now (see migration) and keep I = max(new min, I ÷ 4).
3. 0.3 ≤ m < 0.6: I = I ÷ 2
4. 0 < m < 0.3: I unchanged (cosmetic churn is not a signal)
5. m = 0: I = I × 1.5
6. Clamp I to the tier bounds. Fractions of a day are fine (hours for `live`).
7. Set `last_checked` to today. `next_due` = today + I, then cap by known events: for each event in `events` with a future date, `next_due` = min(`next_due`, event date + `settle_days`). Events are a ceiling, never a floor.
8. Clear `contradiction`. Append `{date, m, interval_after, note}` to `history`.

Worked example (`moderate`, 14 to 90 days, rounded for display): a quiet field walks 30 → 45 → 68 → 90 and settles at the cap. A shake-up (m = 0.7) pulls 90 → 22.5; quiet checks then walk 34 → 51 → 76 → 90. Three consecutive real changes (m = 0.4): 90 → 45 → 22.5 → 14 (pinned at min, see migration). A `slow` unit at 120 days that finds a core claim wrong (m = 0.9) goes to 30 days and becomes `moderate` in one check.

## Tier migration

Topics change character. After each check:

- Immediate promotion: a major change (m ≥ 0.6) whose quartered interval falls below the tier's min moves the unit one tier faster right away. `fast` and `live` have nowhere faster to go; they pin at min and count.
- Promote after a streak: the interval was clamped at the min bound for 2 consecutive checks with m ≥ 0.3. Move one tier faster and set I to the new tier's min. `fast` (or `live`) pinned this way three times in a row becomes `verify_at_use: true`: `next_due` is cleared, scheduling stops, and the volatile claims are re-checked at use instead, each one when it is due (PROTOCOL.md §3: a plain string is due at every use; an object is due `recheck_days` after its `checked` date).
- Demote (slower tier): the interval sat at the max bound for 3 consecutive checks with m = 0. Move one tier slower; I stays at the current value (which is inside the new bounds).
- `verify_at_use` turns back off when two consecutive use-time checks find nothing; the unit returns to `fast` at its start interval.
- Migration drops any custom `bounds_days` (they belonged to the old tier). `code` and `none` never migrate.

The script tracks `streak.pinned_min`, `streak.pinned_max`, and `streak.quiet` for this. By hand, count from `history`.

## Script

`scripts/evergreen.py checked <unit> --m 0.4 --note "CONSORT 2026 revision"` applies all of the above, adds ±15% jitter to `next_due` so many units do not all come due the same day (the stored interval stays unjittered), and prints the result. `evergreen.py next <unit> --m 0.4` is a dry run. The script is canonical when available; the hand rule gives the same interval, and a `next_due` within the jitter band.

## How the rule compares

`python scripts/bench_intervals.py [--seed N] [--days 730] [--json]` runs this rule, imported from `evergreen.py` rather than copied, on synthetic units whose facts change as a Poisson process (plus a regime-shifting class and a release-like bursty class), next to a fixed interval that spends the same number of checks, the tier's start interval held fixed, a fixed 14 days, a FreshCache-style constant interval per class, and an oracle that checks at every change. It reports detection delay per change and per material change (m ≥ 0.3), the share of time a material change goes unseen, and checks per year. The change model is synthetic, so the numbers compare schedules; they do not forecast a unit. The first results and what they suggest are RESEARCH.md R-20260923-10; the rule itself is unchanged, since changing it is asked of the owner first (AGENTS.md), and the proposals are open questions there.

## Test failures are a signal, not a magnitude

A failed test or a failure in use does not set `m`; it sets `tests.failing` and, through `evergreen.py failed`, decides whether research comes before the fix: yes when `last_checked` is older than `tests.research_after_days` (default half the current interval, clamped to 3 to 30 days), and always for the classes `no-op` and `fallback`. The refresh that follows scores its findings on the normal rubric and reschedules as usual; the fix itself is a `C-` entry `because: T-..., L-...`. A refresh that edits a skill's main file re-runs its suite before `checked` is recorded (PROTOCOL §4 step 6).

## Cold start

A converted unit whose topic has a known "last changed" date can start at 10% of the time since that change (the HTTP heuristic-freshness rule), clamped to tier bounds. Otherwise use the tier's start interval. Set `last_checked` to the date of the research that produced the current content, not to the conversion date, so a stale-on-arrival unit is caught by the install audit.
