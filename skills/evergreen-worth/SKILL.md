---
name: evergreen-worth
description: "Judge whether a skill is worth its tokens or useless, one skill or a whole catalog at once: what it costs in every session's listing and every use, how often it really fires (transcripts, tests excluded), whether its baselines already pass without it, what a fresh model already knows (knowledge probe), then the with-versus-without A/B that decides KEEP, TRIM or CUT, plus a person's FIX or SUPERSEDED ruling. Use while making or updating a skill ('is this skill worth it', 'am I overdoing this skill', 'does this skill actually help', 'is this skill useless', 'should I cut this skill', 'is it bloated', 'trim this skill', 'which of my skills are dead weight', 'audit my skills for uselessness', 'is X superseded'), after evergreen-new, evergreen-refresh or evergreen-tune edits a SKILL.md, and when the edit hook prints [evergreen-worth]. Not for proving a skill triggers and acts (evergreen-test), fixing one that failed (evergreen-tune), or rewording descriptions and the listing budget (skill-tidy)."
---

# Evergreen worth

A skill costs tokens in every session (its listing line) and on every use (its body), and the 2026 evidence says most skills do not repay it: 39 of 49 public software skills gave no pass-rate gain, over 60 percent of a typical skill body is not actionable, and self-written skills score below no skill until tested (RESEARCH.md R-20260930-1 to R-20260930-3). This skill finds out which kind the user's skill is, and says so plainly. Rules, thresholds and the five failure modes: `<plugin root>/protocol/TESTING.md` §8.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux).

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish this task, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: the static read (seconds, free)

```
EG worth <skill folder | SKILL.md | plugin root | folder of skills> [--against HEAD]
EG worth <repo or plugin> <another> ... --triage          # a catalog: one row per skill, costliest per use first
```

It prints cost (listing and body, estimated tokens), the share of sentences with a specific anchor, general advice, repeats, hard imperatives, the nearest enabled skill by description, overlap with the repo's README, AGENTS.md or CLAUDE.md, bundled files never named, and:

- `uses`: Skill calls in transcripts over 60 days (`--days N`), split interactive / subagent / headless. Headless runs are tests, never use.
- `evidence`: value cases, their recorded baselines (passed, failed, never run; an undated prediction is not a run), and cases graded only on the skill's own script.
- `mode N`: the failure modes the evidence points to (1 never fires, 2 already known, 3 no gain, 4 worse, 5 superseded), and `gap`: what is unmeasured.

`--against <rev>` judges an edit (`HEAD` while editing, the last tag after a series). Relay warnings, modes and gaps in one or two lines each. The static read can only warn; SUSPECT never proves the skill helps or hurts.

For a catalog, the triage order is the work order: probe everything, A/B the costliest and most doubtful first, and let a skill that is clearly used and already proven skip the A/B, saying why.

## Step 2: the knowledge probe (a minute; for SUSPECT, CHECK, mode 2, or "does Claude already know this")

```
EG worth <skill folder> --probe [--prompt "<a realistic task>"] [--model sonnet] [--out <dir>]
```

A headless run with no skills and no tools says how it would do the job (default prompt: the skill's first value case). It reports which of the skill's key anchors the answer named and which it missed, and saves the answer. Then read the answer against the three to five instructions the skill most depends on: each one already followed unprompted is a trim candidate; each one missed or wrong is what the skill is for. Report both lists. Anchors are a heuristic; the reading is the judgement.

## Step 3: the A/B (the proof)

1. Value cases: at least one `action` or `outcome` case in `evals/evals.json`, a realistic task graded on evidence outside the transcript (TESTING.md §2). A case the model passes without the skill proves nothing; write the harder one the skill exists for (`evergreen-test` Step 2). A case graded only on the skill's own script proves the route; add one graded on the result.
2. Harness, either:
   - `EG worth <skill folder> --ab [--case "action-*"] [--runs 3] [--model M] [--var vault=<path>]`: `claude -p` in fresh temp folders, with and without, on any OS including native Windows. It writes `aggregate-result.json` and reads it at once.
   - `claude plugin eval <plugin root> --trust-plugin --no-publish --case "action-*"` after `EG eval-export <unit>` (a standalone skill: `EG worth <skill> --wrap <dir>` first). Cases that grant Bash need WSL2 on Windows.
   Add `--runs 5` when a result lands inside the noise margin.
3. Read it: `EG worth <skill> --results <dir> --record`. The verdict compares pass rates against a noise margin and weighs the gain against cost, turn and time ratios; `--record` writes it to `evergreen.json` (`worth`), and the audit shows `worth:CUT`, `TRIM`, `SUSPECT`, `FIX`, `SUPERSEDED` or `UNUSED`.

Check that the skill fired first: the harness says when it never fired in the with arm (send it to `evergreen-tune` as `undertrigger` before judging content) or fired in the without arm (contaminated baseline). It also says what it could not grade (placeholders, judge-only expectations): grade those by hand or pass `--var`.

## Step 4: say it, then act only on the user's word

| Verdict | Means | Do |
|---|---|---|
| KEEP | a gain beyond noise at a fair cost, or the same result for less | say so with the numbers |
| TRIM | a real gain at 1.5x the cost or more, or with a suspect body | propose cuts (what the probe showed is already known, repeats, text the repo's docs hold, detail that can move to `references/`); on a yes make them, re-run the A/B, keep the trim only if the gain holds |
| FIX | a repairable failure: never fires because of its description, or misses one thing the probe shows matters | propose the fix and the test that proves it (skill-tidy for a description; a value case for content) |
| CUT | worse with the skill, no gain at a higher cost, or already passing without it | say plainly it costs more than it returns; before proposing removal, try in order: fix triggering, cut to the specific, turn prose into a script, merge into a sibling, narrow it |
| SUPERSEDED | a better-maintained tool now does the job | name it with a dated source |
| SUSPECT | no A/B yet, and the static read says mostly cost | stop adding to it; run Steps 2 and 3 first |
| UNPROVEN | no A/B yet, or a result inside the noise | write a value case or add runs |

Record a ruling the user makes with `EG worth <skill> --set <VERDICT> --why "..." [--replaced-by "..."]`; it survives later `--record` runs. Retiring, parking or disabling a skill needs the user's explicit yes, and is reversible: say how to undo it.

Log each run in the unit's `TESTS.md` (`T-` entry: harness, pass with and without, cost ratio, verdict, `led to:`) and each trim or fix as a `C-` entry whose `because:` cites it.

## While working: capture learnings

A false warning, a probe anchor list that misled, a verdict the user overruled and why, or a harness that could not run: write it to the plugin's LEARNINGS.md with Trigger and Hypothesis, so the thresholds can be tuned with evidence.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
