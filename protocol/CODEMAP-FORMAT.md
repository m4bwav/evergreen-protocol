# Codemap Format

Part of the [Evergreen Protocol](PROTOCOL.md). A codemap is the plugin's own persistent map of a repository or system, built while exploring it so the exploration is not repeated. It is a compass, not an encyclopedia: short, opinionated about what matters, honest about what it has not seen. Evidence: [../RESEARCH.md](../RESEARCH.md) R-20260901-5 (auto-generated bloated context files measurably hurt agents; short human-grade maps help).

## Standing caveat

Every map is written by an agent during a session that had a specific question in mind. It may be out of date, incomplete, or confused. A reader must treat claims as leads, verify anything load-bearing by reading the code, and check drift before trusting structure. The map says this about itself in its header, every time.

## Where maps live

Canonical copy: `EVERGREEN_HOME/maps/<slug>/` containing `CODEMAP.md`, `evergreen.json`, `LEARNINGS.md` (repo gotchas beyond the map), `CHANGELOG.md`. This store belongs to the plugin, so it works for repos you cannot write to (work repos, vendored code, other people's projects).

Optional export: `<repo>/docs/CODEMAP.md` (or next to `AGENTS.md`) when the repo welcomes it. Ask once per repo; record the answer as `export_to_repo` in the map's `evergreen.json`. The store copy remains canonical; the export is a rendering.

Slug: git remote name when there is one (`github.com/owner/repo` → `owner--repo`), else the folder name plus a 6-character hash of the absolute path. `evergreen.py map-slug <path>` computes it.

## Confidence markers

Mark every claim:

- `✓` verified: read the code or ran the command this session or a logged later one
- `~` inferred: from names, structure, docs, or partial reading
- `?` unverified: from a README, a comment, memory, or hearsay

A section with no marker is `~`. Upgrading `~` to `✓` as questions get answered is how the map improves.

## Template

```markdown
# CODEMAP: <name>

<!-- evergreen · generated-at <sha or n/a> · verified <date> · coverage: <dirs seen> · not seen: <dirs> -->
> Built by an AI during exploration for specific questions (log at the bottom). May be out of date, incomplete, or confused. Verify load-bearing claims in the code. Drift check: `git log --oneline <sha>..HEAD | wc -l` (or `evergreen.py drift`).

## What it is
Three to five sentences: problem domain, who uses it, what "done" means here. Not the tech stack.

## Stack and commands
Languages, frameworks, versions. Build / test / lint / run / migrate commands, each marked ✓ if actually run. Copy-pasteable.

## Entry points
main(), route tables, CLI commands, cron, queue consumers. File plus symbol name, no line numbers (they rot).

## Codemap
| Directory | Responsibility | Notes |
Coarse modules only. A map of the country, not an atlas of every town.

## Critical flows
Two to five numbered traces of the flows that matter: "checkout: A → B → C → D". These are what a future session needs to change something safely.

## State, config, environment
Sources of truth (DB, files, caches), which wins on conflict. Where env vars are READ, config precedence, where secrets live (never the secrets).

## Invariants and boundaries
Rules the code assumes, especially absences: "nothing in model/ imports from views/". Layer boundaries. These cannot be found by grepping.

## Gotchas
Fragile files, "touching X silently breaks Y", flaky tests, race conditions, surprising defaults. Pure accumulated pain; the most valuable section.

## Not explored
Directories and subsystems the map has not looked at. Explicit, so the next reader does not assume coverage.

## Questions answered here
| Date | Question | Files read | Outcome |
Append one row per session that used the map. This is the map's provenance and its coverage record.
```

Budget: 150 lines. When the Gotchas or Questions sections outgrow it, move older rows to `CODEMAP-ARCHIVE.md`.

## When to build or update

Build a map when exploring a repo or system to answer a question and it is plausible you will see this repo again. Update it when a later question adds coverage, contradicts a claim, or reveals a gotcha. Do it as you go: after each substantial exploration, spend a minute writing what you learned into the map rather than letting it evaporate with the session.

Use the `evergreen-mapper` subagent for the initial build of a large repo so the exploration does not consume the main context; it returns a draft map that you review before saving.

## Staleness

Tier `code`: due on the calendar (default 30 days, bounds 7 to 90) or on drift, whichever first. Drift thresholds (in `evergreen.json`): 30 commits or 20% of tracked files changed since the stamped sha. A due map is not rebuilt from scratch: re-verify the sections the drift touched (`git diff --stat <sha>..HEAD` shows which directories moved), update the sha, log a `C-` entry. Sections untouched by drift keep their markers.

## What a map is not

Not a dump of every file. Not a copy of the README. Not a place for secrets, credentials, customer data, or anything the repo's owner would object to seeing outside the repo. When mapping a work or client repo, keep the map to structure and procedure; if in doubt about what may leave the repo, keep the map in the store only and never export it.
