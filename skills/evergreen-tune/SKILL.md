---
name: evergreen-tune
description: "Fix a skill or plugin that failed a test or failed in use: it did not trigger, it described an action without performing it (said it delegated, never delegated), it did the job by a forbidden route, or it produced the wrong result. Reproduces the failure in a fresh context, classifies it, writes the learning, researches the subject's testing and tooling when the unit's research is stale, makes the smallest edit, and re-runs the suite. Use on 'X didn't do Y', 'the skill never delegated', 'the skill didn't trigger', 'fix this skill', 'tune X', 'why did X fail', 'X keeps doing it wrong', or when evergreen-test reports a failure or a unit shows failing tests. Not for application bugs; that is the repo's job."
---

# Evergreen tune

The bounded loop that turns a failure into a fix with a reason. Rules: `<plugin root>/protocol/TESTING.md` §5; research gate in `protocol/INTERVALS.md`. Three iterations per session, then stop and report.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux (whichever answers `-c "import sys"`; the hook probes the same way)).

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish this task, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: get the failure on record

Two entry points:

- From `evergreen-test`: the case ids and evidence are in hand; `evergreen.json.tests.failing` already lists them.
- From use: the user says the skill did not do something, or the use log shows it. Find what actually happened before deciding anything: `EG uses --skill <name>` lists recent invocations (Claude Code; the PostToolUse hook writes them) with their `transcript_path`; read that transcript for the tool calls after the Skill invocation. In Cowork there is no use log; rely on the user's account and on what is on disk. Then write the case into `evals/evals.json` if none covers it (prompt as the user phrased it, kind, evidence), and record it:

```
EG failed <unit> --case <id> --class <undertrigger|overtrigger|no-op|fallback|wrong-outcome|environment|harness> --note "<one line>"
```

It adds the case to `tests.failing`, prints the next `T-` id, and gives the research verdict for Step 4. An installed read-only copy: work on `evergreen.json.source`.

## Step 2: reproduce and classify

Run the case through the `evergreen-tester` agent (or the harness in TESTING.md §6) three times in fresh contexts, with the evidence the case names. Compare against the baseline in the case. Then classify by what the evidence shows, not by what the reply says:

- `undertrigger`: the skill was not invoked on a trigger prompt.
- `overtrigger`: a decoy invoked it.
- `no-op`: invoked; the action was narrated or planned; the evidence is absent. The delegation-that-never-delegated case.
- `fallback`: the job got done by another route (curl instead of the tool, local instead of remote, a guess instead of a lookup).
- `wrong-outcome`: the action happened; the result is wrong.
- `environment`: a path, port, permission, credential or tool is missing where the skill runs.
- `harness`: the case or the evidence check is wrong; the skill did its job.

A failure that does not reproduce in three runs is `flaky`: record the traces in the `T-` entry, leave the case in `failing`, and stop after Step 3.

## Step 3: write the learning now

`evergreen-learn` gate: Add, Update, or None against the unit's LEARNINGS.md. Trigger (what the evidence showed, with the run count), Hypothesis (why the skill did that), Rule (what would have prevented it). `environment` failures route to `profile/ENVIRONMENTS.md` with a pointer in the unit.

## Step 4: research gate

`EG failed` printed one of two verdicts. `research due`: the unit's research is older than `tests.research_after_days` (default half its interval, 3 to 30 days), or the class is `no-op` or `fallback`, which usually means the tool, API or route the skill depends on moved. Run `evergreen-refresh` on the unit now with the testing track leading: how others verify and enforce this action for this subject, what changed in the tools the skill depends on, which checker or harness they use, whether a maintained skill or server now does this job. Findings become `R-` entries and may change the fix in Step 5. `research not due`: go straight to Step 5.

## Step 5: the smallest edit, by class

- `undertrigger` / `overtrigger`: the description. Add the user's actual phrasing; add a negative clause naming the decoy's job. With skill-creator installed, use its description improver (held-out prompts, up to five iterations, keep the best by held-out score). Never pad the body to fix triggering.
- `no-op`: give the action step its own verification: "run X; confirm by reading Y; do not report done until Y exists", naming the evidence. Where the action is deterministic, move it into `scripts/` and have the step run the script. Check `allowed-tools` and the tool's availability where the skill runs. A no-op that reproduces after this fix is usually `environment` in disguise.
- `fallback`: name the required tool or route and forbid the alternative in one line with the reason ("the Mac's Ollama, not the local model: the point is the GPU there").
- `wrong-outcome`: fix the step that produced it; add one example of the correct shape.
- `environment`: a precondition check at the top of the skill (what to verify, what to tell the user when it fails) plus the profile learning from Step 3.
- `harness`: fix the case, not the skill.

Edit in place, delta only. One class, one edit, then re-run; do not stack fixes before measuring.

## Step 6: re-run and record

The failing case three times, then the whole suite (`evergreen-test` Step 3). Then:

```
EG tested <unit> --passed N --failed M [--failing ids] --harness <name> --note "<class: what changed>"
```

Write the `T-` entry in TESTS.md with `led to: L-..., C-..., R-...`; log the `C-` entry in CHANGELOG.md with `because: T-..., L-...` (and `R-...` when Step 4 ran); back-fill `applied:` on any finding. When the run is clean, `failing` is cleared by `tested`; `EG flag <unit> --clear-failing <id>` clears one by hand.

Still failing: next iteration from Step 2 with the new evidence. After the third, stop.

## Step 7: report

At most three lines: the class and what changed, pass counts before and after, and anything that needs a decision. After three failed iterations: what was tried, whether the tooling track found a maintained tool the skill should delegate to instead, and whether the skill should be retired. Leave `tests.failing` set so Step 0 keeps saying so.

## While working: capture learnings

The loop itself teaches: a class that was hard to tell from another, an evidence type that could not be collected in some environment, a fix that made triggering worse. Write those to the plugin's LEARNINGS.md with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
