---
name: evergreen-audit
description: "List every evergreen unit (skills, docs, codemaps, profiles) with its tier, last check, due date, staleness, drift, test status (untested, overdue, failing), link integrity, and budget problems, then refresh what is due. Use right after installing or updating the evergreen plugin (it may have sat on a shelf), at the start of work in a new environment, on 'evergreen status', 'what's stale', 'audit my skills', 'check the skills', 'anything due', or whenever a session-start hook reports due units. Also the place to register units the plugin does not know about."
---

# Evergreen audit

One table, then action. Protocol: `<plugin root>/protocol/PROTOCOL.md` §7.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux (whichever answers `-c "import sys"`; the hook probes the same way)).

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, the plugin itself is the first stale unit in the table below; refresh it first (`evergreen-refresh`, unit = plugin root) after reporting.

## Step 1: run the audit

```
EG audit --checks
```

It merges the registry (`EVERGREEN_HOME/registry.json`) with a shallow scan of the usual roots (the plugin, the store's `units/` and `maps/`, the current folder, `~/.claude/skills`, `.claude/skills`, `.agents/skills`) and prints one line per unit: name, kind, tier, last check, due date, status (fresh / STALE / n/a), flags (contradiction, verify-at-use with `claims due N`, drift, failing-tests, untested, tests-overdue, `consolidate:N>M` for active learnings past `consolidate_every`, installed copy, source not visible), plus link and lint problems when `--checks` is on (a skill with no `evals/evals.json`, a suite with TODO prompts or no action case, a plan missing a research track, a `Related:` line with an unknown label or a target that does not exist). `--json` for machine output; `--roots <paths>` to scan elsewhere.

No shell reaching the files (a sandbox that cannot see the host)? Run it on the host through a host-side tool if one exists (Desktop Commander `start_process` in Cowork), or read each `evergreen.json` you can reach and apply the freshness rule by hand: STALE if `contradiction` is set or today ≥ `next_due`; `n/a` for tier `none` and `verify_at_use` units, and for the latter count the due claims (a plain string is always due; an object is due when `checked` plus `recheck_days`, default `interval_days`, is today or earlier).

## Step 2: register what is missing

If the user mentions a unit the audit did not list, `EG register <unit-dir>`. If a skill clearly should be evergreen but is not, say so once and offer `evergreen-convert`; do not convert unasked.

## Step 3: act on what it found

- STALE units: do not refresh silently in bulk. Tell the user which are due (the plugin itself first), then run `evergreen-refresh` for them in this session unless the user is mid-task, in which case queue them for after. On install, refreshing the plugin's own research is the priority: its portability table and spec details move fastest.
- Contradiction flags: those refresh at the minimum interval; mention what was contradicted (it is in `evergreen.json.contradiction.note`).
- `failing-tests`: a skill with a known failure (`evergreen.json.tests.failing`); offer `evergreen-tune` for it, first if the user is about to use that skill. `untested` (suite never run) and `tests-overdue` (last run older than twice the interval): queue `evergreen-test` for when the unit is next touched; a skill with no suite at all gets `EG test-init` and cases written when the user agrees.
- `claims due N` (verify-at-use units): those claims are re-checked the next time the unit is used (its Step 0), not now, unless the user is about to rely on one; `EG claims <unit> --due` lists them.
- `consolidate:N>M`: queue a consolidation pass with `evergreen-learn` for after the user's task.
- Drifted codemaps: re-verify the touched sections next time the repo is used (`evergreen-map`), not now, unless the user is about to work in that repo.
- Link and lint problems: fix mechanical ones now (a missing back-link, a learning without a Trigger, an ID referenced but never defined, a `Related:` target that moved). Budget overruns get archived (`*-ARCHIVE.md` with a pointer) or a consolidation pass via `evergreen-learn`.
- Installed copies: list which need a reinstall or republish because their source changed. "Source not visible from here" means the running copy may itself be the source seen through a mount; say so and continue.
- Unsent update bundles (`EG where` lists them): the plugin changed itself here and the email did not go out; run `evergreen-notify`.
- The use log (`EG where` shows it; `EG uses` lists recent skill invocations, Claude Code only): a skill invoked often is worth a suite; a skill never invoked in weeks may be undertriggering or unneeded, say so once.

## Step 4: report

The table (or the stale subset when there are many), then at most three lines: what was refreshed or fixed, what is queued, what needs the user. Nothing stale and no problems: one line saying so.

## Install check

After installing this plugin anywhere: run this skill once. If `EG contribute` says "not decided", ask the user the question it prints (once, in plain words) and record the answer with `EG contribute yes|no`; until then nothing leaves the machine. It confirms the store (`EG home`), creates the registry if missing, registers the plugin and its profile (`EG register <plugin root>` and `EG register <plugin root>/profile`; registering the plugin also records `plugin_root` in the registry, which pointer-mode units resolve their protocol through), and flags the plugin as due if its own `next_due` passed while it sat unused. Then `EG where`: it takes the install baseline from the shipped `MANIFEST.json` when the files are still pristine (otherwise `EG baseline --from <the pack zip>`), and shows whether an update transport is ready (`smtp_ready`, or Outlook/Graph on Windows); if none is, say which one the user could set up (`evergreen-notify` §Step 4). Record the environment in `<plugin root>/profile/ENVIRONMENTS.md` if it is new (which tools reach which paths, whether hooks run, where the store is, which transport sends mail).

## While working: capture learnings

Audit surprises (a root that should be scanned, a false STALE, a path the sandbox could not reach) go into the plugin's LEARNINGS.md with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
