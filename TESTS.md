# Tests: evergreen

Test runs for the plugin's own skills ([README.md](README.md) is the unit's main file; the cases exercise `skills/*`). Cases live in `evals/evals.json`; `evals/fixtures/sample-skill/` is a throwaway unit the action cases operate on (copy it to a temp folder first). A failure that taught something is a lesson in [LEARNINGS.md](LEARNINGS.md); a fix it caused is logged in [CHANGELOG.md](CHANGELOG.md) with `because: T-...`; research it triggered is in [RESEARCH.md](RESEARCH.md); counts and the failing list are in `evergreen.json` under `tests`. Rules: `protocol/TESTING.md`.

A test passes on evidence (a tool call in the trace, a file, a marker, a log line), never on the transcript's claim that something was done.

Entry shape: `### T-YYYYMMDD-n · date · harness · env · passed/total`, then one line per failing case (`id · kind · class · what the evidence showed`), then `led to:` (L-, C-, R- ids or none). Newest first. Budget 150 lines; archive older runs to `TESTS-ARCHIVE.md`.

## Runs

### T-20260923-3 · 2026-09-23 · claude plugin eval 2.1.280 on cases written by `evergreen.py eval-export`, one run each; trigger-2 rerun · owner-pc · 3/3
- `eval-export . --out evals-export-probe` wrote all 12 cases of this plugin's suite; through `--eval-dir evals-export-probe`, the exported trigger-4 fired evergreen-learn (its `input_match` is the exact pattern the docs give for a Skill call, and it matched) and the exported decoy-2 kept every evergreen skill quiet with and without the plugin. The probe folder was deleted afterwards; the hand-tuned `evals/cases/` stay as they are.
- trigger-2 (evergreen-test) rerun after its Step 3 named `eval-export`: 3 of 3 with the plugin, 0 of 3 without.
- led to: C-20260923-15

### T-20260923-2 · 2026-09-23 · claude plugin eval 2.1.280 (trigger and decoy cases, sonnet judge, --no-publish) · owner-pc · 9/9
- Trigger 6/6 (trigger-1 tune, trigger-2 test, trigger-3 refresh, trigger-4 learn, new, trigger-5 audit, new, trigger-6 publish): the Skill tool fired with the matching skill in 3 of 3 runs each with the plugin and 0 of 3 without (18 of 18 against 0 of 18); the judge passed every routing reply. Decoys 3/3 on the rerun: the Skill tool fired 0 times in 9 of 9 runs with the plugin and 9 of 9 without, 18 of 18 quiet runs with the plugin across both decoy runs.
- decoy-1 and decoy-3 · trigger · harness · the first decoy run failed 1 and 2 of 3 with-plugin runs on the `llm` grader only: the replies declined correctly but named `evergreen-test` as not fitting, or passed on the plugin's session-start question about contributing (always undecided in the harness's throwaway home). The rubric forbade words, not behaviour; rewritten (L-023), rerun 3/3.
- Not run: action-1, action-2 and outcome-1. The action cases grant Bash, which the harness refuses on native Windows (L-019), and no edit in this release changed the actions they exercise. `--case "trigger-[2-5]"` and `--case "trigger-{2,3,4,5}"` selected nothing; one `*` glob per call.
- Harness notes: every run in a throwaway home, config and workspace; trigger results come from a `claude -p` child with the plugin loaded, a proxy for the main loop. List-price estimate 1.21 + 3.56 + 1.26 USD, about 3.5 minutes of wall time at `-j 4`. Results in `evals/results/` (ignored by git).
- led to: L-023, C-20260923-12 (L-019 updated with the glob finding)

### T-20260923-1 · 2026-09-23 · scripts/bench_intervals.py --seed 1 --days 730 (synthetic benchmark of the interval rule) · owner-pc · 3/3
- Passes = the three properties the smoke test checks on every run: repeatable for a seed, the matched schedule spends exactly the rule's checks per unit, the oracle's delay is 0. The scores are a benchmark, not a pass mark. 25 synthetic units per class, 9 classes, one use a day for verify-at-use units:

| Policy | Checks per year | Mean delay, all changes (days) | Mean delay, material (days) | Time holding a stale material claim |
|---|---|---|---|---|
| evergreen (the rule) | 43.2 | 42.9 | 42.3 | 17.4% |
| matched (rule's count, even spacing) | 43.2 | 50.1 | 51.6 | 13.6% |
| tier-start (no adaptation) | 52.0 | 37.5 | 34.8 | 18.1% |
| fixed-14 | 26.0 | 7.0 | 6.8 | 17.6% |
| freshcache (per-class half-life) | 467.7 | 6.3 | 6.2 | 5.6% |
| oracle | 36.7 | 0.0 | 0.0 | 0.0% |

- The delay columns are means per class averaged over classes, so the slow classes (and the 730-day horizon's tail) dominate them; per class, the rule's delay on material changes is 1.24 to 1.65 times the matched schedule's in 8 of 9 classes. Ten years (seed 1): the rule 34.3 checks a year and 18.4 percent stale, matched 14.0, tier-start 18.1, fixed-14 17.4, freshcache 5.7 at 468 checks; the ratio is 1.27 to 1.71 in all 9 classes. Seeds 2 and 3 at 730 days: the rule 17.8 and 17.9 percent, matched 13.5 and 14.1, fixed-14 17.3 and 17.2. Reading and per-class numbers: RESEARCH.md R-20260923-10. untested elsewhere (a pure-Python simulation; CI runs the smoke version on three operating systems).
- led to: R-20260923-10, C-20260923-9, open questions in RESEARCH.md (damped steps or a change-rate anchor, promotion on one major change, FreshCache-style starting intervals, a research budget)

### T-20260913-1 · 2026-09-13 · claude plugin eval 2.1.269 (trigger, decoy, outcome) + evergreen-tester agent (action) · owner-pc · 10/10
- Trigger 4/4 (trigger-1 tune, trigger-2 test, trigger-3 refresh, trigger-6 publish): the Skill tool fired 3 of 3 runs each with the plugin, 0 of 3 without it; the sonnet judge passed every routing reply. Decoys 3/3 (repo unit tests, an application bug that mentions delegation, a feature-branch PR): no evergreen skill fired in any of 18 runs, with or without the plugin. outcome-1 3/3 on the deterministic regex (the judge failed one correct reply; the regex is the check that counts). action-1 3/3 and action-2 3/3 through the tester agent with trace and file evidence: `evergreen.py init` (or `test-init`) in every action-1 run and all six companion files on disk; `evergreen.py failed ... --class no-op` in every action-2 run and `tests.failing = ["action-1"]` in the copy's evergreen.json.
- Redundant: action-1 and action-2 both pass with the skill absent (the prompts name the script, and a fresh agent finds `init`, `test-init` and `failed --class no-op` from `--help`). They prove the script, not the skills; sharpen them by withholding the script path, or by asking for the conversion the way a user would ("make this skill self-maintaining") and grading on the skill's extra work (four-track search plan filled, pointer MAINTENANCE.md, tier chosen with a reason).
- Harness notes: trigger results from the harness are a proxy for the main loop (a `claude` child with the plugin loaded, `allowed_tools` without Bash). On Windows the harness refuses any run that grants Bash (L-019), so action cases run through the tester agent, one fresh context per run. Cases live in `evals/cases/<id>/` (harness form, generated from `evals/evals.json`); results in `evals/results/` (ignored by git). Cost: about 8 USD across the harness runs.
- led to: L-019, C-20260913-2

### T-20260904-1 · 2026-09-04 · not yet run · home-pc-cowork · 0/8
- Suite written with version 0.5.0: three trigger prompts (tune, test, refresh), two decoys (a repo's own tests; an application bug that mentions delegation), two action cases with trace-or-file evidence against the fixture unit, one outcome case with a regex check. Not run in the session that wrote it: the installed copy there was 0.4.0, which has no `evergreen-test` or `evergreen-tune` skill, so a trigger run would have measured nothing. First run: after installing 0.5.0, `evergreen-test` on the plugin root through the tester agent (or `claude plugin eval` where enabled), which also fills the `baseline` fields.
- led to: none
