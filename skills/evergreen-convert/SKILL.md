---
name: evergreen-convert
description: "Convert an existing skill, plugin, knowledge document, or repo doc into a self-maintaining evergreen unit: adds RESEARCH.md, CHANGELOG.md, LEARNINGS.md, evergreen.json, for skills a TESTS.md and evals suite, a Maintenance section in the main file, and either a link to the plugin's protocol or a standalone MAINTENANCE.md companion. Use on 'make X self-maintaining', 'convert X to evergreen', 'add research refresh to X', 'make this skill keep itself current', 'evergreen-ify', or when auditing skills that still refresh ad hoc (a hand-rolled state file, a 'refresh every N days' note) and should join the paradigm."
---

# Evergreen convert

Bring an existing unit into the protocol without rewriting it. Protocol: `<plugin root>/protocol/PROTOCOL.md`; tiers: `protocol/INTERVALS.md`; modes: `protocol/PORTABILITY.md`.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path.

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish the conversion, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: understand the unit

Read the main file (SKILL.md, or the doc) and anything it points to. Answer:

- Topic: what would web research keep current? One line. Nothing researchable (personal preferences, private facts, project procedure) → tier `none`.
- Tier: from the INTERVALS.md rubric ("if wrong for a month, how bad?", "how often did the source change last year?"). Confirm with the user via one question when the choice is not obvious.
- Existing maintenance: a hand-rolled state file, a "refresh every N days" note, a research section, a changelog? Preserve their content, migrate their state (last refresh date, interval, history) into `evergreen.json`, and remove the duplicate mechanism so there is one source of truth.
- Time-sensitive claims: list the claims in the main file that could go stale. They seed the subject track of the search plan and, for very volatile ones, `volatile_claims`.
- Tooling and practice: does the unit re-implement something the ecosystem now ships as a skill, plugin, MCP server or script? One pass of the tooling queries (PROTOCOL §4) answers that; the result goes into RESEARCH.md as the first tooling finding, and a supersession is worth telling the user about before converting.
- Evidence: for a skill, what does its core action leave behind that a test could check (a tool call, a file, a remote record)? If the answer is nothing, the skill narrates and the first test will say so; note it now for Step 3.
- Mode: can the unit reach the plugin's `protocol/` by relative path (it lives in or next to the plugin, or a repo that vendors it under `.agents/`)? Then link it. Otherwise, default to pointer mode (`--pointer`): `evergreen.json.protocol` is the word `plugin`, resolved through the store's registry to the one installed plugin, and a short `MAINTENANCE.md` says how to find it plus the few stable rules needed if it is missing. The unit then never changes when the protocol does. Use full standalone (`--standalone`, a complete `MAINTENANCE.md` copy) only for a unit that will travel to machines with no plugin at all.
- Writable? If the folder is an installed copy (a Cowork plugin or saved skill, a marketplace install), convert the source folder instead and set `--source`.

## Step 2: scaffold

```
EG init <unit-dir> --name <name> --topic "<topic>" --kind skill --tier <tier> --main SKILL.md \
   --last-checked <date of the research behind the current content> \
   [--pointer | --standalone | --protocol ../../protocol/PROTOCOL.md] [--source <path>] --append-maintenance
```

`init` never overwrites existing files: it writes the missing companions from templates (for skills also `TESTS.md` and `evals/evals.json`), appends the Step 0 / learnings / Maintenance sections to the main file, sets the schedule, and registers the unit. A unit converted before the testing pillar existed gets the suite with `EG test-init <unit>`. `--last-checked` matters: set it to when the content was actually researched, so a stale-on-arrival unit is caught by the next audit instead of being trusted for a full interval.

No shell reaching the folder? Copy the templates from `<plugin root>/templates/` by hand and fill the `{{PLACEHOLDERS}}` (`DATEID` is the date without dashes); write `evergreen.json` using the plugin's own as a model.

## Step 3: fill, do not stub

- RESEARCH.md: write Current understanding from what the main file already asserts; put the time-sensitive claims into the Search plan's subject track as concrete queries and fill in the tooling, practice and testing tracks from the template with `<topic>` replaced; list best primary sources; add an `R-` entry summarizing the research basis of the current content, plus one for what the tooling pass found (or did not find) (even if that basis is "written from model knowledge on <date>", say so; that is exactly what the first refresh should check).
- CHANGELOG.md: the conversion entry, plus any history you migrated.
- LEARNINGS.md: migrate any lessons already embedded in the main file as tips or warnings if they carry a reason; otherwise leave the file with its header only. Do not invent lessons.
- evals/evals.json (skills): write the trigger cases from the description's own phrases, two decoys from neighbouring skills, one action case with the evidence found in Step 1, one outcome case. Do not run the suite unasked; offer it (`evergreen-test`), since a first run on an old skill often finds the no-op the user converted it to fix.
- Main file: keep the author's structure. If it had its own staleness or refresh section, replace it with the appended Maintenance section and a pointer, then log that in the changelog.

## Step 4: verify

`EG links <unit>` and `EG lint <unit>`. Fix anything reported. Then `EG status <unit>`: if the unit is already past due (old research), tell the user and offer to run `evergreen-refresh` now; if it has a suite that has never run, offer `evergreen-test`.

## Step 5: report

Three lines: what was added, the tier and next due date, and whether a reinstall or republish is needed for an installed copy (Cowork `save_skill` skills need `save_skill overwrite`; Cowork plugins need the `.plugin` reinstalled; local-path Claude Code installs need nothing).

## Converting many

When asked to convert several, do them one at a time with the steps above and finish with `EG audit --checks`. Ask before touching skills the user did not name.

## While working: capture learnings

Conversions surface tool quirks (a skill store that is read-only, a template placeholder that did not fit). Record them in the plugin's LEARNINGS.md with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
