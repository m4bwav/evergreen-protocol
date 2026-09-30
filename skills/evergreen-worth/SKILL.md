---
name: evergreen-worth
description: "Judge whether a skill is worth its tokens, and warn when it is mostly cost: what it adds to every session's listing and every use, how much is specific (commands, paths, values the model cannot guess) rather than advice the model already follows, what an edit added, overlap with other skills and the repo's docs, then the with-versus-without A/B that decides KEEP, TRIM or CUT. Use while making or updating a skill ('is this skill worth it', 'am I overdoing this skill', 'does this skill actually help', 'is this skill useless', 'should I cut this skill', 'is it bloated', 'trim this skill', 'which of my skills are dead weight'), after evergreen-new, evergreen-refresh or evergreen-tune edits a SKILL.md, and when the edit hook prints [evergreen-worth]. Not for proving a skill triggers and acts (evergreen-test) or fixing one that failed (evergreen-tune)."
---

# Evergreen worth

A skill costs tokens in every session (its listing line) and on every use (its body), and the 2026 evidence says most skills do not repay it: 39 of 49 public software skills gave no pass-rate gain, over 60 percent of a typical skill body is not actionable, and self-written skills score below no skill until tested (RESEARCH.md R-20260930-1 to R-20260930-3). This skill finds out which kind the user's skill is, and says so plainly. Rules and thresholds: `<plugin root>/protocol/TESTING.md` §8.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux).

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish this task, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: the static read (seconds, free)

```
EG worth <skill folder | SKILL.md | plugin root | folder of skills> [--against HEAD]
```

`--against <rev>` judges the edit since that commit: use `HEAD` while a skill is being changed, the last release tag after a series of edits. It prints the listing and body cost (estimates, about four characters a token), the share of sentences that carry a specific anchor, general-advice sentences, repeats, hard imperatives, the nearest other skill by description, overlap with the repo's README, AGENTS.md or CLAUDE.md, bundled files the skill never names, recent uses from the use log, and a verdict. A folder of skills prints one row each. Relay any warning to the user in one or two lines; do not paste the whole report unless asked.

The static read can only warn. SUSPECT means "mostly cost on reading"; it never proves the skill helps.

## Step 2: the knowledge probe (minutes, cheap; for SUSPECT, CHECK, or "does Claude already know this")

Pick the three to five instructions the skill most depends on. Ask a fresh context with the skill absent (the `evergreen-tester` agent told to treat the skill as absent, or `claude -p` from a folder where it is not installed) how it would do the skill's job, one realistic prompt, no hints. Every instruction the answer already follows unprompted is a trim candidate; every one it gets wrong or misses is what the skill is for. Report both lists.

## Step 3: the A/B (the proof)

1. Value cases: the skill's `evals/evals.json` needs at least one `action` or `outcome` case: a realistic task the skill exists for, graded on evidence outside the transcript (a file, a value, a regex; TESTING.md §2). A case the model passes without the skill proves nothing; write the harder one the skill was made for. No suite yet: `evergreen-test` Step 2 writes it.
2. Harness: `claude plugin eval` runs every case with the plugin and without it, three runs per arm by default. A skill inside a plugin: `EG eval-export <unit>`, then `claude plugin eval <plugin root> --trust-plugin --no-publish --case "action-*"` (and again for `outcome-*`). A standalone skill: `EG worth <skill> --wrap <scratch dir>` builds a throwaway plugin around it and prints both commands. Cases that grant Bash need a sandbox (WSL2 on native Windows). Add `--runs 5` when the first result lands inside the noise margin.
3. Read it: `EG worth <skill> [--results <dir>] --record`. It takes the latest with-and-without result per value case, compares pass rates against a noise margin (about a 95 percent two-sided test, never less than one run's worth), and weighs the gain against the cost, turns and time ratios. `--record` writes the verdict to `evergreen.json` (`worth`), and the audit then shows `worth:CUT`, `worth:TRIM` or `worth:SUSPECT`.

skill-creator's benchmark (`benchmark.json`, with and without) is the same comparison; when it is the harness, apply the §8 rules to its numbers by hand.

## Step 4: say it, then act only on the user's word

| Verdict | Means | Do |
|---|---|---|
| KEEP | a gain beyond noise at a fair cost, or the same result for less | say so with the numbers; nothing to cut |
| TRIM | a real gain at 1.5x the cost or more, or a real gain with a suspect body | propose the cuts (general-advice sentences, repeats, text the repo's docs already hold, detail that can move to `references/`), make them on the user's yes, re-run the A/B, keep the trim only if the gain holds |
| CUT | worse with the skill, or no gain beyond noise at a higher cost, or the model already passes without it | tell the user plainly that the skill is costing more than it returns; offer to retire it (disable, or delete with its folder) and never do either without an explicit yes |
| SUSPECT | no A/B yet, and the static read says mostly cost | stop adding to the skill; run Steps 2 and 3 before any more work on it |
| UNPROVEN | no A/B yet, nothing suspect, or a result inside the noise | write a value case (Step 3.1) or add runs |

Before any content verdict, check that the skill fires: a with-arm that never invoked it measures nothing (the `tool_used: Skill` grader, or `EG uses --skill <name>`). A skill that does not trigger goes to `evergreen-tune` as `undertrigger` first. A static SUSPECT on a skill the A/B calls KEEP is still worth a trim pass: the gain may hold with less text.

Log the run in the unit's `TESTS.md` (`T-` entry: harness, pass with and without, cost ratio, verdict, `led to:`) and any trim as a `C-` entry with `because:` citing it.

## While working: capture learnings

A false warning (a specific sentence the anchors missed, a sibling pair flagged although it is fine), a verdict the user overruled and why, or a harness that could not run the A/B: write it to the plugin's LEARNINGS.md with Trigger and Hypothesis, so the thresholds can be tuned with evidence.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
