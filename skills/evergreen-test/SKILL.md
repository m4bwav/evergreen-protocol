---
name: evergreen-test
description: "Write and run the eval suite that proves a skill or plugin works: trigger prompts and decoys, action cases proven by evidence outside the transcript (a tool call in the trace, a file, a marker, a remote record), outcome cases, and a baseline without the skill. Use when a skill has just been written (with evergreen-new or skill-creator), after a refresh or a tune edited a skill, on 'test this skill', 'does X actually trigger', 'run the evals', 'prove X works', 'regression test the skills', 'write tests for X', or when the audit lists untested or overdue units. When a case fails, hand over to evergreen-tune. Not for testing application code; that is the repo's own test suite."
---

# Evergreen test

Prove a unit with evidence, log the run, and hand failures to the tuning loop. Rules: `<plugin root>/protocol/TESTING.md` (the shape is in PROTOCOL.md §11). The failure this exists for is the skill that says it delegated and never did.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path.

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish this task, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: locate the unit and its suite

The unit folder holds `evergreen.json`. Skills and plugins carry tests; docs, codemaps and profiles do not (say so and stop). No `evals/evals.json` yet: `EG test-init <unit>` scaffolds `evals/evals.json`, `TESTS.md` and the `tests` block. An installed read-only copy: work on `evergreen.json.source`.

Read `evals/evals.json`. Cases still holding `TODO` prompts need writing (Step 2); a written suite goes to Step 3.

## Step 2: write the cases

Read the skill's description and body first. Then, per TESTING.md §1:

- Trigger: at least two prompts phrased the way the user actually asks (take them from the description's trigger phrases and from any real request in the conversation), `runs: 3`, expectation "the skill is invoked".
- Decoys: at least two nearby prompts that must not trigger it (a sibling skill's job, plain conversation about the same nouns), `decoy: true`.
- Action: at least one prompt whose fulfilment requires the skill's core action, with `evidence` named concretely: `{type: trace, tool, input_match}` for a tool call, `{type: file, path}` or `{type: marker}` for something the action leaves behind, `{type: command, run, expect}` for a check the caller can execute, `{type: log, path, pattern}` for a log line. For a delegation skill the evidence is the remote job id, the remote log line, or the file the remote side writes back; the local reply is not evidence. If no evidence can be named, the skill's action step needs to leave some; say so, and route that to `evergreen-tune` as class `no-op` before the suite is run.
- Outcome: at least one prompt with a deterministic check (a value, a regex on the output, a file's content) and, only if needed, one quality criterion for a judge.

Keep prompts short and realistic. Do not tell the case which skill to use; a trigger case that names the skill tests nothing.

## Step 3: baseline, then run

Pick the harness from TESTING.md §6, first that exists: `claude plugin eval` (Claude Code, early access; `--case`, `--runs 3`, graders `tool_used` on `Skill`, `file_exists`, `regex`), skill-creator's runner (its `evals/evals.json` is ours), otherwise the `evergreen-tester` agent, one case per call, or a headless CLI (`claude -p ... --output-format stream-json`, `copilot -p`, `codex exec`) with the `tool_use` events captured. In Cowork the tester agent is the harness; prefer action evidence the main session can check on disk.

1. Baseline once per action and outcome case: the same prompt in a fresh context with the skill absent (tell the tester not to load it; or run before the skill is installed). Record what happened in the case's `baseline` field, one line. A case that passes without the skill is redundant: sharpen it or mark it.
2. Run every case `runs` times (default 3) in fresh contexts. Collect the evidence the case names; for trigger cases, the Skill tool call in the trace or the tester's report of the skills it invoked.
3. Judge per TESTING.md §7: trigger 2 of 3, decoy 0 of 3, action and outcome every run with evidence. Never grade an action case on the reply's wording.

Cost: a suite is a handful of prompts times three runs; run it at creation, after an edit, after a failure, on request. Not on every use.

## Step 4: record

```
EG tested <unit> --passed N --failed M [--failing id,id] --harness <name> --note "<one line>"
```

It updates `evergreen.json.tests` and prints the next `T-` id. Write that entry at the top of `TESTS.md`: harness, environment, passed/total, one line per failing case (`id · kind · class · what the evidence showed`), redundant cases if any, and `led to:` (fill in after tuning; `none` for a clean run). Trigger results from a subagent are a proxy for the main loop: say so in the entry.

If any case failed: hand over to `evergreen-tune` in this session with the case ids and the evidence collected. Do not edit the skill here.

## Step 5: report

At most three lines: passed/total by kind, failing case ids and their likely class, and whether the suite passed without the skill (retirement candidate). For the plugin's own skills, `EG tested` also sends the update digest unless `--no-notify`.

## While working: capture learnings

A harness that could not run a case, evidence that could not be collected where the skill runs, a prompt that turned out ambiguous: write it to the unit's LEARNINGS.md (or the plugin's, when the lesson is about testing itself) with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
