---
name: evergreen-map
description: "Build or update the plugin's own codemap of a repository or system while exploring it, so the exploration is never repeated. Use when the user asks how an unfamiliar or recurring codebase, service, or system is put together ('walk me through this repo', 'what talks to what', 'where is Y configured', 'how does X handle auth' in a repo you will plausibly see again), when you are about to grep around an unfamiliar repo, or on 'map this repo', 'update the codemap', 'is the map stale'. Before answering from an existing map, check drift first: maps can be out of date, incomplete, or confused. Not for one-off questions in a repo with no future, and not a replacement for a repo-specific skill that already covers that repo (use both: the specific skill for the task, this one to keep the map current)."
---

# Evergreen map

Keep a short, honest map of every system you explore. Format and rules: `<plugin root>/protocol/CODEMAP-FORMAT.md`. Maps are compasses, not encyclopedias (auto-generated bloat measurably hurts agents); every claim carries a marker (✓ verified, ~ inferred, ? unverified) and the map logs which questions it has actually answered.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux (whichever answers `-c "import sys"`; the hook probes the same way)); optional.

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish the user's task, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: is there a map already?

Compute the slug: `EG map-slug <repo-path>`. Look in `EVERGREEN_HOME/maps/<slug>/` (`EG home` prints the store) and, if the repo has one, `docs/CODEMAP.md`. Found one: `EG drift <map>` (or `git log --oneline <sha>..HEAD | wc -l`). Read the map, note its coverage line and "Not explored" section, and treat everything as leads to verify, not facts. Drift past threshold or the calendar due: re-verify the sections the changed directories touch as part of the work, then update the sha (`EG drift <map> --update-sha`).

## Step 2: answer the question, mapping as you go

Work the user's question first. While reading code, keep a running list of: entry points touched, directory responsibilities confirmed, flows traced, config and state locations, invariants noticed, and anything surprising. Mark each ✓ only if you read the code or ran the command; ~ if inferred from names, structure, or docs; ? if it came from a README, comment, or memory.

For a large unfamiliar repo, delegate the initial sweep to the `evergreen-mapper` agent (repo path, the question, and what to focus on). It returns a draft map you review; never save a draft you did not read.

## Step 3: write or update the map

New map: `EG map-init <repo-path> --name <name>` creates the unit in the store from the template (stamps the sha and remote). Fill the sections you actually have evidence for; leave the others as one-line placeholders under "Not explored". Keep it under 150 lines.

Existing map: delta edits. Upgrade markers as claims get verified, add gotchas, extend flows, correct anything the code contradicted (and log a `C-` entry saying what was wrong). Append a row to "Questions answered here": date, question, files read, outcome. Update the coverage comment in the header.

What never goes in a map: secrets, credentials, customer data, anything the repo owner would object to seeing outside the repo. For work or client repos keep the map to structure and procedure.

## Step 4: export (optional, ask once)

If the repo welcomes docs, offer once to export the map to `docs/CODEMAP.md` and record the answer as `export_to_repo` in the map's `evergreen.json`. The store copy stays canonical. Never export a map of a repo you are not allowed to commit to.

## Step 5: tell the user

One line: map created or updated, where, and how much of the repo it covers. If the map contradicted the code somewhere, say what changed.

## While working: capture learnings

Repo gotchas ("touching X silently breaks Y", flaky tests, surprising defaults) go in the map's Gotchas section. Procedural lessons about mapping itself (a tool that helped, a directory pattern that misled you) go in the map unit's `LEARNINGS.md` with Trigger and Hypothesis, or in the plugin's LEARNINGS.md when general.

## Maintenance

Maps are tier `code` units: due on the calendar (30 days by default, 7 to 90) or on drift (30 commits or 20% of files), whichever first; they never migrate tiers. This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
