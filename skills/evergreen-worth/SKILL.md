---
name: evergreen-worth
description: "Judge whether a skill is worth its tokens, one skill or a catalog, as a lite scan in seconds or a heavy measured run: its cost per session and per use, how often it really fires (tests excluded), whether baselines pass without it, what a fresh model already knows, then the with-versus-without A/B that decides KEEP, TRIM or CUT, plus a person's FIX or SUPERSEDED ruling. Use while making or updating a skill ('is this skill worth it', 'am I overdoing this skill', 'does this skill actually help', 'is this skill useless', 'should I cut this skill', 'is it bloated', 'trim this skill', 'which of my skills are dead weight', 'audit my skills for uselessness', 'is X superseded', 'quick check of my skills', 'test this skill thoroughly'), after evergreen-new, evergreen-refresh or evergreen-tune edits a SKILL.md, and when the edit hook prints [evergreen-worth]. Not for proving a skill triggers and acts (evergreen-test), fixing a failure (evergreen-tune), or rewording descriptions (skill-tidy)."
---

# Evergreen worth

A skill costs tokens in every session (its listing line) and on every use (its body), and the 2026 evidence says most skills do not repay it: 39 of 49 public software skills gave no pass-rate gain, over 60 percent of a typical skill body is not actionable, and self-written skills score below no skill until tested (RESEARCH.md R-20260930-1 to R-20260930-3). This skill finds out which kind the user's skill is, and says so plainly. Rules, thresholds and the five failure modes: `<plugin root>/protocol/TESTING.md` §8.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux).

## Lite or heavy

- **Lite** (`EG worth <skill> --lite`, seconds, no model calls): cost, use, recorded evidence, the static read and a lint of the value cases, as one issue list. Use it first, on every skill in a catalog, and after any edit. The case lint finds what would waste a paid A/B: a placeholder the runner cannot fill, a `check` it cannot run, an outcome case without Edit or a shell, `redundant` used to hide a case, a check behind a path a right answer may never write, an `evals.json` that does not parse.
- **Heavy** (`EG worth <skill> --heavy --model sonnet --out <dir> [--case GLOB] [--max-usd 15] [--no-probe]`): refuses while the case lint finds problems (`--force` overrides), then runs the probe, the A/B on every value case with 3 runs per arm, and top-up runs to 5 per arm while the gain sits inside the noise margin, stopping before `--max-usd` (probe included). Then Steps 3 to 5 below. Use it for a verdict someone will act on.

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

1. Value cases: at least one `action` or `outcome` case in `evals/evals.json`, a realistic task graded on evidence outside the transcript (TESTING.md §2). A case the model passes without the skill proves nothing; write the harder one the skill exists for (`evergreen-test` Step 2). A case graded only on the skill's own script proves the route; add one graded on the result:
   - a small stdlib checker in `evals/` that judges the end state and exits 0 only when it is right, used as a file evidence `"check": "python evals/check_x.py <dir> exits 0"` whose `path` is a file the fixture already has, so the checker is the whole judge;
   - prove the checker before paying for runs: exit 0 on a hand-made correct copy and on the skill's own output, exit 1 on the untouched fixture and on each wrong variant you can think of;
   - grade the reply in the same case with `regex on the answer:` expectations (graded together with the evidence);
   - give an outcome case that changes files `"tools": ["Edit", "Bash(python *)", ...]` and `max_turns`; never mark a case `redundant` unless it passed without the skill.
   Run `--lite` until the case lint is clean.
2. Harness, either:
   - `EG worth <skill folder> --ab [--case "action-*"] [--runs 3] [--model M] [--var vault=<path>]`: `claude -p` in fresh temp folders, with and without, on any OS including native Windows. It writes `aggregate-result.json` and reads it at once.
   - `claude plugin eval <plugin root> --trust-plugin --no-publish --case "action-*"` after `EG eval-export <unit>` (a standalone skill: `EG worth <skill> --wrap <dir>` first). Cases that grant Bash need WSL2 on Windows.
   Add `--runs 5` when a result lands inside the noise margin.
3. Read it: `EG worth <skill> --results <dir> --record`. The verdict compares pass rates against a noise margin and weighs the gain against cost, turn and time ratios; `--record` writes it to `evergreen.json` (`worth`), and the audit shows `worth:CUT`, `TRIM`, `SUSPECT`, `FIX`, `SUPERSEDED` or `UNUSED`.

Check that the skill fired first: the harness says when it never fired in the with arm (send it to `evergreen-tune` as `undertrigger` before judging content) or fired in the without arm (contaminated baseline). It also says what it could not grade (placeholders, judge-only expectations): grade those by hand or add `--var`. Runs marked `environment` (the skill not in the with arm's init event, writes refused as sensitive files, a usage limit) are left out of the counts; when any appear, read one transcript and fix the harness before reading the numbers. Before trusting a 0 percent arm, re-run the checker by hand on one kept run folder (`workdir` in `aggregate-result.json`): a grader that cannot find its script fails every run silently.

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

## Step 5: feed it back into the skill (every heavy run, on a branch)

Whatever the verdict, the skill under test gets what the run taught, as one pull request the user reviews:

- its `LEARNINGS.md`: what the probe and the baseline showed the model already does, and what it missed or got wrong;
- its `evals.json`: the result-graded cases and checker, the case-lint fixes;
- a token-saving list with the expected saving for each: listing text that never triggered, body text the probe or the baseline showed is already known, detail that only some uses need (move it to `references/`, read on demand), rules the bundled script already enforces or its `--help` already says (point at the script), and multi-step prose a script flag could do in one call (fewer turns). Make the savings that do not touch the description or the instructions the A/B depends on; re-run the A/B on the trimmed skill and keep a cut only if the pass rate holds. A description change waits for its trigger cases to pass again.

Retiring, parking or removing the skill is still the user's ruling.

## While working: capture learnings

A false warning, a probe anchor list that misled, a verdict the user overruled and why, or a harness that could not run: write it to the plugin's LEARNINGS.md with Trigger and Hypothesis, so the thresholds can be tuned with evidence.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](https://github.com/m4bwav/evergreen-protocol/blob/master/RESEARCH.md), [CHANGELOG.md](https://github.com/m4bwav/evergreen-protocol/blob/master/CHANGELOG.md), [LEARNINGS.md](https://github.com/m4bwav/evergreen-protocol/blob/master/LEARNINGS.md), [TESTS.md](https://github.com/m4bwav/evergreen-protocol/blob/master/TESTS.md).
