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

If the user said "plain skill", "no maintenance", "one-off", or the topic has nothing to research and nothing to learn, build a normal skill and stop here. Otherwise proceed; mention in one line that the skill will be evergreen (tier and interval) so the user can object.

## Step 2: design the skill

Use `skill-creator` if it is available for intent capture, the SKILL.md draft, and any evals. Otherwise follow its essentials: a pushy third-person description with concrete trigger phrases; an imperative body under 200 lines; detail in `references/`; deterministic work in `scripts/`; examples of output shape.

While designing, separate two lists:

- Time-sensitive claims: anything that could change on the web (tool versions, APIs, prices, policies, best practices, model behavior). These become the subject track of the search plan and set the tier.
- Procedure and preference: how the user wants the work done. These are learnings material and, if fixed, go straight into the body.

Then run the tooling track before writing the body (PROTOCOL §4 and §8): GitHub code search `path:SKILL.md "<topic>"`, skills.sh or `npx skills find "<topic>"`, the MCP registry search, `"<topic>" skill OR plugin OR "mcp server" <year> site:github.com`. If a well-used, maintained skill, plugin or server already does the job, the new skill builds on it or points at it instead of re-implementing it; tell the user what was found and let them decide before installing anything. Add one or two practice queries (how others use AI agents on this goal) and one or two testing queries (what evidence shows this job was done, what checker or harness others use for it) so the plan has all four tracks from day one.

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

Fill RESEARCH.md properly: Current understanding (what the skill asserts and how confident you are, including what tooling exists for the subject), Search plan in its four tracks (subject: the time-sensitive claims as queries with primary sources; tooling, practice and testing: the template's queries with `<topic>` filled in and anything better found today), and an `R-` entry per track recording what today's research found, a one-liner when a track was quiet. If the skill was written from model knowledge without a web check, say so in the `R-` entry and set `--last-checked` to today anyway; the first refresh will do the verification. For `fast` and `live` topics, do the web check now: model knowledge is almost always stale there.

## Step 4: prove it, then hand over

`EG links <skill-dir>` and `EG lint <skill-dir>`. Then `evergreen-test`: fill `evals/evals.json` (at least two trigger prompts in the user's own phrasing, two decoys, one action case with evidence outside the transcript, one outcome case), run the baseline without the skill, run the suite, log the `T-` entry. skill-creator's own eval loop and description improver, when installed, are the harness; the suite is in its format. A failing case goes to `evergreen-tune` before hand-over, three iterations at most.

Tell the user: skill name, where it lives, tier and next due date, the test result (passed/total by kind, any case still failing and why), and that it will announce when it is due or has a failing test and act after the task. A skill is never handed over on the strength of its description alone.

## Placing it

- Inside this plugin: `skills/<name>/`.
- Portable, cross-tool: `.agents/skills/<name>/` in the repo (with the plugin exported to `.agents/` via `EG export <repo>`, or `--standalone`), mirrored into `.claude/skills/` (PORTABILITY.md).
- Cowork saved skill: also `save_skill` the SKILL.md; the folder on disk stays the source of truth and `source` points at it.

## While working: capture learnings

Authoring friction (a frontmatter field a tool rejected, a template placeholder that did not fit) goes into the plugin's LEARNINGS.md with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
