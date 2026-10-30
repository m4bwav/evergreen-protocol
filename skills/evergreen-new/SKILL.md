---
name: evergreen-new
description: "Add the self-maintaining layer to a skill being created (research refresh on an adaptive schedule, learnings capture, changelog, an eval suite that proves it triggers and acts, double-linked companion files) and pick its tier. Use whenever the user asks to create, write, draft, or scaffold a skill, command, or plugin skill ('make me a skill for X', 'new skill', 'turn this into a skill'), unless they explicitly ask for a plain skill with no maintenance. The authoring itself is skill-creator's job (or create-cowork-plugin's for a whole plugin); this skill runs alongside, after the SKILL.md draft exists, and adds evergreen."
---

# Evergreen new

New skills are evergreen by default. This skill wraps whatever skill-authoring process is available (Anthropic's `skill-creator` when present; otherwise the guide below) and adds the maintenance layer. Protocol: `<plugin root>/protocol/PROTOCOL.md` §8; tiers: `protocol/INTERVALS.md`.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux (whichever answers `-c "import sys"`; the hook probes the same way)).

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish the skill, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: confirm the default

If the user said "plain skill", "no maintenance", "one-off", or the topic has nothing to research and nothing to learn, build a normal skill and stop here. Otherwise proceed; mention in one line that the skill will be evergreen (tier and interval) and that it starts with a deep research pass, so the user can object.

## Step 2: design the skill

Use `skill-creator` if it is available for intent capture, the SKILL.md draft, and any evals. Otherwise follow its essentials: a pushy third-person description with concrete trigger phrases; an imperative body under 200 lines; detail in `references/`; deterministic work in `scripts/`; examples of output shape.

While designing, separate two lists:

- Time-sensitive claims: anything that could change on the web (tool versions, APIs, prices, policies, best practices, model behavior). These become the subject track of the search plan and set the tier.
- Procedure and preference: how the user wants the work done. These are learnings material and, if fixed, go straight into the body.

Then run the creation pass before writing the body (PROTOCOL §8): a deep web research run on all four tracks, whatever the tier, so the skill starts at the state of the art and never has to be taught a lesson the field already learned. Launch `evergreen-researcher` in creation mode, one pass per track or pair of tracks in parallel, each given the topic, the draft's time-sensitive claims and the track's queries from the RESEARCH template; with no subagents, run the same searches inline. At least five queries per track and eight or more fetched pages in all:

- Subject: official docs, changelogs, standards, key papers and reference works, the official forums of each tool the skill depends on; the current best way to do the job and what changed this year.
- Tooling: GitHub code search `path:SKILL.md "<topic>"`, skills.sh or `npx skills@1.7.0 find "<topic>"`, the MCP registry, Anthropic's plugin catalogs, `"<topic>" skill OR plugin OR "mcp server" <year> site:github.com`; read the top one to three candidates in full (SKILL.md, scripts, evals, open issues). If a well-used, maintained one already does the job, the new skill builds on it or points at it; tell the user what was found and let them decide before installing anything.
- Practice: how people use AI agents on this goal and what they learned the hard way: workflows, prompts, pitfalls, failure reports in the top tools' issue trackers, forum and subreddit threads, Hacker News, dated case studies. Each lesson that changes how the work should be done becomes a step or a guard in the body, with its `R-` finding as the source.
- Testing: what evidence shows this job was done and what checkers or harnesses others use, so the first cases use them.

Without web access, say so, build the draft, and leave `next_due` at today so the first use runs the pass; never hand over a skill researched from model knowledge alone as finished.

Write the core action step so it leaves evidence: name the file, tool call, or record it produces and make the step confirm it before reporting done. A step that can only be checked by reading the reply cannot be tested and will fail the suite as a no-op.

Pick the tier with the INTERVALS.md rubric. Topic with no time-sensitive claims → `none`. Unsure → `moderate`. Ask the user only when two tiers are both plausible.

Put deterministic steps in a script when that is a net token saving without noise or mistakes (PROTOCOL.md §8): scaffold, checks, packing, probes; keep judgment in the skill text. Design for every platform unless the user says otherwise (PROTOCOL.md §8, PORTABILITY.md §Cross-platform by default): stdlib Python or POSIX `sh`, `pathlib` paths, `~` and per-OS maps for locations, UTF-8 and LF, no platform tool without a branch or a message. A platform-only feature is fine when the general route would be onerous; say which platforms the skill covers in its description.

## Step 3: scaffold with the layer

Create the folder, write SKILL.md, then:

```
EG init <skill-dir> --name <name> --topic "<one line>" --kind skill --tier <tier> --last-checked <today> \
   [--pointer | --standalone] --append-maintenance
```

Skills inside the plugin, or in a repo that vendors the plugin under `.agents/`, link to `../../protocol/PROTOCOL.md`. A skill that lives elsewhere on a machine that has the plugin (a tool's skill store, its own folder) gets `--pointer`: its protocol is the installed plugin, found through the registry, so the skill does not change when the plugin updates. `--standalone` (a full `MAINTENANCE.md` copy) is for a skill that will travel to machines with no plugin.

Then the beat offer (PROTOCOL.md §8, "A beat for a new unit"): `EG scout offer <skill-dir>`. Exit 1 with no output means everscout is not installed or the unit was asked before: say nothing. Exit 0 prints the question: ask it once, in those words. Yes: `EG scout create <skill-dir>`, then run `everscout-beat` on the printed beat from source discovery onward, so the beat ends verified. No: `EG scout decline <skill-dir>`. For a plugin of several skills, offer once for the plugin's unit, not per skill.

A skill that needs anything outside itself (a tool, a package, a key, a server, a model, an MCP server, an account) gets `SETUP.md` now: `EG setup <skill-dir> --init`, one Needs row per dependency with what it is for and its fallback, recipes only where the shared book (`setup/RECIPES.md`) does not cover it, a link from SKILL.md's Step 0, then `EG setup <skill-dir> --log` once the check passes here (PROTOCOL.md §12, `evergreen-setup`).

Fill RESEARCH.md properly: Current understanding (what the skill asserts and how confident you are, including what tooling exists for the subject), Search plan in its four tracks (subject: the time-sensitive claims as queries with primary sources, plus the official forum of each tool, platform or vendor the skill depends on, with its URL and announcements category, such as devforum.roblox.com for a Roblox skill or discussions.unity.com for Unity; tooling, practice and testing: the template's queries with `<topic>` filled in and anything better found today), and the creation pass's findings as `R-` entries (one per material finding, at least one per track, a one-liner when a track was quiet), the first of them carrying the pass's cost line. Search plan queries that worked in the creation pass replace the template's generic ones.

## Step 4: prove it, then hand over

Worth first (`evergreen-worth`, TESTING.md §8): `EG worth <skill-dir>` on the draft. SUSPECT or a warning means the draft is mostly advice the model already follows, bloat, or a near copy of another skill: tell the user in one or two lines and cut before building the suite, since a self-written skill scores below no skill until it is tested. `EG links <skill-dir>` and `EG lint <skill-dir>`. Then `evergreen-test`: fill `evals/evals.json` (at least two trigger prompts in the user's own phrasing, two decoys, one action case with evidence outside the transcript, one outcome case), run the baseline without the skill, run the suite, log the `T-` entry. skill-creator's own eval loop and description improver, when installed, are the harness; the suite is in its format. A failing case goes to `evergreen-tune` before hand-over, three iterations at most.

With an action or outcome case run under `claude plugin eval`, read the A/B with `EG worth <skill-dir> --record` and hand over its verdict; a CUT goes to the user as a recommendation not to keep the skill.

## Step 5: launch-ready (units with their own repository)

A skill set or plugin that gets its own repository ships with the launch set of PROTOCOL §8: the owner's repository conventions first (from their profile or agent instructions), else a README that opens with a hero image (use an installed image-generation skill), install and quick-start sections, LICENSE, SECURITY.md, CI running the unit's checks, AGENTS.md and CLAUDE.md pointers, description and topics, and a GitHub wiki (use an installed wiki skill; the first wiki page must be saved in the web interface before a push works, so name that step when it is owed). Check each item off or list it as owed.

## Hand-over

Tell the user: skill name, where it lives, tier and next due date, what the creation pass found (its cost line, the tools it builds on or points at, the two or three practice lessons that shaped the body), the test result (passed/total by kind, any case still failing and why), the worth verdict, the launch set's status when there is a repository, and that it will announce when it is due or has a failing test and act after the task. A skill is never handed over on the strength of its description alone.

## Placing it

- Inside this plugin: `skills/<name>/`.
- Portable, cross-tool: `.agents/skills/<name>/` in the repo (with the plugin exported to `.agents/` via `EG export <repo>`, or `--standalone`), mirrored into `.claude/skills/` (PORTABILITY.md).
- Cowork saved skill: also `save_skill` the SKILL.md; the folder on disk stays the source of truth and `source` points at it.

## While working: capture learnings

Authoring friction (a frontmatter field a tool rejected, a template placeholder that did not fit) goes into the plugin's LEARNINGS.md with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](https://github.com/m4bwav/evergreen-protocol/blob/master/RESEARCH.md), [CHANGELOG.md](https://github.com/m4bwav/evergreen-protocol/blob/master/CHANGELOG.md), [LEARNINGS.md](https://github.com/m4bwav/evergreen-protocol/blob/master/LEARNINGS.md), [TESTS.md](https://github.com/m4bwav/evergreen-protocol/blob/master/TESTS.md).
