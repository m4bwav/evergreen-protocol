# Tests: evergreen

Test runs for the plugin's own skills ([README.md](README.md) is the unit's main file; the cases exercise `skills/*`). Cases live in `evals/evals.json`; `evals/fixtures/sample-skill/` is a throwaway unit the action cases operate on (copy it to a temp folder first). A failure that taught something is a lesson in [LEARNINGS.md](LEARNINGS.md); a fix it caused is logged in [CHANGELOG.md](CHANGELOG.md) with `because: T-...`; research it triggered is in [RESEARCH.md](RESEARCH.md); counts and the failing list are in `evergreen.json` under `tests`. Rules: `protocol/TESTING.md`.

A test passes on evidence (a tool call in the trace, a file, a marker, a log line), never on the transcript's claim that something was done.

Entry shape: `### T-YYYYMMDD-n · date · harness · env · passed/total`, then one line per failing case (`id · kind · class · what the evidence showed`), then `led to:` (L-, C-, R- ids or none). Newest first. Budget 150 lines; archive older runs to `TESTS-ARCHIVE.md`.

## Runs

### T-20260913-1 · 2026-09-13 · claude plugin eval 2.1.269 (trigger, decoy, outcome) + evergreen-tester agent (action) · owner-pc · 10/10
- Trigger 4/4 (trigger-1 tune, trigger-2 test, trigger-3 refresh, trigger-6 publish): the Skill tool fired 3 of 3 runs each with the plugin, 0 of 3 without it; the sonnet judge passed every routing reply. Decoys 3/3 (repo unit tests, an application bug that mentions delegation, a feature-branch PR): no evergreen skill fired in any of 18 runs, with or without the plugin. outcome-1 3/3 on the deterministic regex (the judge failed one correct reply; the regex is the check that counts). action-1 3/3 and action-2 3/3 through the tester agent with trace and file evidence: `evergreen.py init` (or `test-init`) in every action-1 run and all six companion files on disk; `evergreen.py failed ... --class no-op` in every action-2 run and `tests.failing = ["action-1"]` in the copy's evergreen.json.
- Redundant: action-1 and action-2 both pass with the skill absent (the prompts name the script, and a fresh agent finds `init`, `test-init` and `failed --class no-op` from `--help`). They prove the script, not the skills; sharpen them by withholding the script path, or by asking for the conversion the way a user would ("make this skill self-maintaining") and grading on the skill's extra work (four-track search plan filled, pointer MAINTENANCE.md, tier chosen with a reason).
- Harness notes: trigger results from the harness are a proxy for the main loop (a `claude` child with the plugin loaded, `allowed_tools` without Bash). On Windows the harness refuses any run that grants Bash (L-019), so action cases run through the tester agent, one fresh context per run. Cases live in `evals/cases/<id>/` (harness form, generated from `evals/evals.json`); results in `evals/results/` (ignored by git). Cost: about 8 USD across the harness runs.
- led to: L-019, C-20260913-2

### T-20260904-1 · 2026-09-04 · not yet run · home-pc-cowork · 0/8
- Suite written with version 0.5.0: three trigger prompts (tune, test, refresh), two decoys (a repo's own tests; an application bug that mentions delegation), two action cases with trace-or-file evidence against the fixture unit, one outcome case with a regex check. Not run in the session that wrote it: the installed copy there was 0.4.0, which has no `evergreen-test` or `evergreen-tune` skill, so a trigger run would have measured nothing. First run: after installing 0.5.0, `evergreen-test` on the plugin root through the tester agent (or `claude plugin eval` where enabled), which also fills the `baseline` fields.
- led to: none
