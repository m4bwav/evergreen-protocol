# Learnings: evergreen

Procedural lessons about building and running the plugin, for [README.md](README.md) and the skills. Research findings live in [RESEARCH.md](RESEARCH.md); every change is logged in [CHANGELOG.md](CHANGELOG.md); test runs in [TESTS.md](TESTS.md); state in `evergreen.json`. Format and gate: `protocol/LEARNINGS-FORMAT.md`. Promoted, merged and retired entries, each with its reason: [LEARNINGS-ARCHIVE.md](LEARNINGS-ARCHIVE.md).

Lessons about the owner's preferences or environments belong in `profile/`, not here.

## Active

### L-043 · 2026-10-29 · A test stub that prints only the lines the parser wants hides the parser's bug
- Trigger: the first real `scout create` (on a new game design plugin) crashed with "list index out of range" after everscout had created the beat; the unit stayed unlinked.
- Hypothesis: `everscout.py where --beat` prints `BEATS <folder>` lines before `BEAT <slug> = <path>`, and `startswith("BEAT")` matched the folder line first. The stub printed only the BEAT line, so the self-test passed.
- Rule: a stub for another tool's output copies the real output's shape, every line kind included; parse a keyed line by its exact first token.
- Evidence: C-20261029-2; the new stub fails the old code.
- helpful: 1 · harmful: 0

### L-032 · 2026-10-23 · A judge's wording is part of the judge; calibrate on a random sample, never one picked by verdict (`judge-wording-and-random-labels`)
- Trigger: 2026-10-23. 1,109 `llm` verdicts from 104 graders in six repositories' plugin-eval results: three votes split on 5%, and graders packing four or more criteria split no more often (3.8%) than single-criterion ones (6.3%). Re-judging eight replies the harness judge had failed unanimously, the same model (Sonnet) with the same criteria in a differently worded prompt gave 12 PASS votes of 24. Blind labels on those eight agreed with the harness on 6 and with the re-worded judge on 5; the harness's kappa there was 0 by construction, since it had failed all eight. A random 20 of this plugin's own verdicts, labelled blind, agreed 20 of 20 (kappa 1.00).
- Hypothesis: a judge prompt is an instrument; its framing moves borderline verdicts as much as the criteria do. A sample chosen by verdict holds one answer from the judge, so agreement there measures the labeller's base rate, not the judge.
- Rule: calibrate a judge with `judge-sample` (random, verdicts hidden) and `judge-agree`; treat a new grader text, judge model or harness version as a new judge; record all three in the T- entry. Keep one judge per case with its criteria listed: splitting criteria into separate graders bought no stability here.
- Evidence: C-20261023-1; `judge_sample`, `judge_agree`, `kappa`; test `test_judge_sample_hides_verdicts_and_agree_measures_kappa`
- Scope: plugin (TESTING.md §7; evergreen-test)
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-10-23

### L-033 · 2026-10-23 · Padding a reply did not buy a pass; a test of it must keep the reply's required ending (`length-bias-padding-test`)
- Trigger: 2026-10-23. Eight real failing replies doubled with filler: 12 PASS votes of 24 before, 9 after, 6 with the length rule added to the prompt. Six real passes with the rule: 16 of 18 before, 15 after, no majority changed. Three of the eight (legal answers) had to end with a set line; the filler pushed it off the end and those turned to FAIL for that reason, not for length.
- Hypothesis: on short checkable criteria a current judge does not reward length; a long reply still looks better to it when the length carries real coverage, which no padding test can separate from merit.
- Rule: keep the "length is not a criterion" line as a free guard but do not claim it fixes a bias that was not measured; to test length bias, pad in the middle of a reply, never after a required last line.
- Evidence: C-20261023-1 (JUDGE_RULE); test `test_judge_graders_get_the_length_rule_and_a_reference`
- Scope: plugin (TESTING.md §7)
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-10-23

### L-030 · 2026-10-01 · An A/B run can measure its own harness; prove the checker and read the init event before trusting a number (`ab-paths-absolute-check-init`)
- Trigger: obsidian-notes on 2026-10-01. `worth skills/obsidian-notes --ab` with a relative path spent $1.67 on 6 runs that measured the harness: `--plugin-dir .` named each run folder, the with arm never loaded the skill, its writes were refused as sensitive plugin files, and a relative checker path graded three correct baseline vaults 0 of 3, which the report turned into mode 4 "worse at 1.39x the cost". Writing the result-graded cases the same day hit five more traps that would each have spent runs measuring nothing (merged from L-031): outcome cases whose default tools cannot edit a file, `redundant: true` hiding a case and reporting mode 2, a `check` behind a `path` a right answer may never write, answer regexes ignored in cases with `evidence`, and an `evals.json` broken by halved heredoc backslashes that `worth` read as "0 value cases"
- Hypothesis: the runner was tested from inside the skill folder, where relative and absolute paths coincide, and the case format grew for `claude plugin eval` and the tester agent while `--ab` read some fields differently; nothing checked a suite or an arm's loaded skills before the money was spent
- Rule: the harness now resolves paths, classes setup faults as `environment` and lints cases (`worth --lite`; `--heavy` refuses until the lint is clean). What stays with the agent: prove each checker on a hand-made correct copy, the skill's own output and the untouched fixture before any paid run; before trusting an arm at 0 percent, re-run its checker by hand on one kept `workdir`; no mode 3 or 4 when both arms fail everything
- Evidence: C-20261001-1; `evergreen_ab.run_ab`, `localize`, `environment_fault`, `case_prompt`, `grade_case`; `evergreen_worth.case_lint`, `failure_modes`; tests `test_case_lint_finds_what_would_waste_an_ab` and `test_ab_harness_lessons_from_the_obsidian_notes_run`; TESTING.md §8; the re-run on the fixed harness fired the skill in every with-arm run
- Scope: plugin (TESTING.md §8; evergreen-worth, evergreen-test)
- Status: active · helpful 2 · harmful 0 · last_confirmed 2026-10-01

### L-021 · 2026-09-22 · Anchor a new log entry on the newest real heading, never on the first `### C-`
- Trigger: 2026-09-22, an everlast-capture CHANGELOG.md had a C- heading pasted into the middle of its `Entry shape:` line, the rest of that line stranded lower down as a fake `### C-YYYYMMDD-n` heading, and the entries out of order
- Hypothesis: every companion's header quotes the entry template (`Entry shape: `### C-YYYYMMDD-n · ...``), so an insert before the first `### C-` (or `### R-`, `### L-`, `### T-`) text lands inside that line
- Rule: insert before the full heading of the current newest entry (`### C-20260918-1 ·`), or before the first line that starts with `### C-` outside the header; afterwards list the file's `### ` headings and the `Entry shape` line and check the order and that the template is intact
- Evidence: the repaired everlast-capture CHANGELOG.md (2026-09-22); every evergreen companion template has the same header
- Scope: global
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-22

### L-020 · 2026-09-17 · Files written on Windows come out CRLF unless written as bytes, and `* -text` ships them everywhere
- Trigger: 2026-09-17, the privacy scrub for the public repository found `scripts/evergreen-hook.sh` and 40 other files with CRLF; under `sh` on macOS or Linux all three hooks would have died at the first `case` line, unseen because Git Bash strips the `\r`. 2026-09-23: the scripts' own `Path.write_text` rewrote evergreen.json and new companions as CRLF on every `checked`, `bump`, `tested` and `init` on Windows
- Hypothesis: Windows editors and Python's text mode write CRLF by default; `* -text` (needed so pack manifests and patches hash the bytes on disk) means git never normalises, so whatever was written is what every clone gets
- Rule: keep every committed text file LF (`*.sh text eol=lf` on top of `* -text`); scripts write bytes (`write_lf`, since `Path.write_text(newline=)` is Python 3.10+), and an agent on Windows edits with the Edit tool or writes bytes, then checks for `\r`; an evergreen.json that is already CRLF keeps its endings (`save_state`); CI on a second operating system is the proof
- Evidence: C-20260917-2, C-20260923-13, C-20261014-1; tests `test_sh_hook_is_lf_everywhere` and `test_state_and_scaffold_files_are_written_lf`
- Scope: global
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-23

### L-017 · 2026-09-10 · A documented feature can leave the docs without a changelog line; re-check that doc-derived claims are still there
- Trigger: R-20260904-2 recorded `claude plugin eval`'s flags and graders from the plugins reference on 2026-09-04; the 2026-09-10 refresh found the section gone from the plugins reference, the CLI reference and `llms.txt`, with no changelog entry, while the unit still presented the flags as current (it came back with 2.1.269, R-20260923-7)
- Hypothesis: refresh queries look for what is new (changelogs, releases, dated posts); a silent removal sends no such signal, so a withdrawn feature survives in a unit until someone tries to use it
- Rule: keep the read date next to a claim taken from a doc page; at every refresh re-fetch the page behind each claim that names a command, flag or field and confirm it is still there (`llms.txt` or the page's own index is the quick proof); downgrade a vanished claim in place ("documented on <date>, withdrawn by <date>"), never delete it
- Evidence: R-20260910-1, R-20260923-7; the TESTING.md §6 row carries both dates; the plugin-evals claim in evergreen.json
- Scope: skill (evergreen-refresh); a line for agents/evergreen-researcher.md's subject track at its next edit
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-10

### L-016 · 2026-09-06 · `init --append-maintenance` skips the Maintenance section when SKILL.md already mentions evergreen.json
- Trigger: scaffolding five unity-agent skills (2026-09-06), each SKILL.md written first with the template's Step 0 paragraph; `init --append-maintenance` printed "SKILL.md already references evergreen.json; nothing appended", so the `## Maintenance` section had to be added by hand to all five
- Hypothesis: the guard in `scaffold` treats any mention of evergreen.json as proof the whole maintenance block exists, but Step 0 and the Maintenance section are separate pieces
- Rule: when writing SKILL.md before `init`, include both the Step 0 paragraph and the `## Maintenance` section from `templates/MAINTENANCE-SECTION.md.template` yourself, or run `init` on an empty folder first and fill the body afterwards
- Evidence: five manual appends on 2026-09-06 (unity-agent suite); `EG lint` passed afterwards; the guard is unchanged in `scaffold`
- Scope: skill (evergreen-new)
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-06

### L-013 · 2026-09-03 · A mail connector carries attachments as base64 through the model; prefer the Drive picker, and split anything a connector sends
- Trigger: 2026-09-03, the 0.2.0 archive through Claude Code's Gmail MCP: the 150 KB mail zip is about 200 KB of base64, too much for one tool call, so only `plugin.json` and `INSTALL.txt` went. 2026-09-10 (merged from L-018), bundle 20260909-2229 through the Cowork Gmail connector: the 91 KB `changes.patch` became 121,352 base64 characters and the send died with "Output token limit hit" before any message went out; Claude in Chrome with "Insert files using Drive" then attached the patch and the 235 KB mail archive in one message
- Hypothesis: connector attachments are tool-call arguments at about one token per base64 character, so the ceiling is the per-call output budget of the model writing the call, not Gmail's 25 MB or the context; 24 KB pieces (about 33k characters) are marginal
- Rule: when a browser signed into the mailbox is available, attach the mirrored bundle files through the Drive picker in one message, then `notify --mark-sent <bundle> --via chrome-gmail`; use a connector only when every attachment is under ~16 KB raw (`pack --mail --split 16`, `changes.patch` cut the same way, one piece per message in one thread, each read from disk, the base64 prep done by the agent that sends); never base64 a whole archive or patch in one call; prefer the script's own transports (smtp, graph, outlook) when one is set up
- Evidence: C-20260903-4, C-20260913-1; evergreen-notify SKILL.md Step 3; evergreen-pack SKILL.md (Email); the Chrome send recorded in `EVERGREEN_HOME/notify.json` (via chrome-gmail)
- Scope: plugin (evergreen-notify Step 3, evergreen-pack)
- Status: active · helpful 2 · harmful 0 · last_confirmed 2026-09-10

### L-008 · 2026-09-02 · A Cowork save_skill skill with no source folder can use its own data folder as the evergreen unit
- Trigger: converting science-study-evaluator (2026-09-02): the only copy of SKILL.md was the read-only Cowork store, and the skill already kept a hand-rolled state.json and a methodology file in its own data folder
- Hypothesis: the writable folder the skill already reads at run time is the natural source; with SKILL.md and the companions there, a research refresh edits the checklist without re-saving the skill, and only SKILL.md edits need `save_skill overwrite`
- Rule: set the unit dir and `source` to the skill's existing data folder (create one if none); write SKILL.md there with frontmatter, run `init --standalone` without `--append-maintenance` when it already carries its own Step 0, then pass the body without frontmatter to `save_skill` (name and description as parameters); Step 0 must use the absolute unit path, since the installed copy has no evergreen.json beside it
- Evidence: the converted unit (links OK, lint OK, registered 2026-09-02); the skill re-saved and listed with the new description
- Scope: env:home-pc-cowork
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-02

### L-005 · 2026-09-01 · The paradigm's own skills must obey the paradigm, and a reviewer is how you find out they do not
- Trigger: the six shipped skills had a Maintenance footer but no Step 0 freshness check, the exact mechanism the protocol says runs "every use"; the plugin could not notice its own staleness where hooks do not run
- Hypothesis: the template was written after the first skills and never applied back to them
- Rule: after changing a template or protocol rule, re-read every shipped unit against it (or run `audit --checks`), and get one independent review before packaging a version
- Evidence: C-20260901-3
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-01
