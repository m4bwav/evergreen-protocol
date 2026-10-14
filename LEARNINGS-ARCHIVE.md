# Learnings archive: evergreen

Promoted and retired entries from [LEARNINGS.md](LEARNINGS.md), each with the reason: promoted ones were folded into a main file (the `promoted:` change and the parenthesis say where); retired ones were merged into another entry, or their rule is now enforced by a script or test or written in a main file (the Status line names where). Kept as the reasoning lineage so a retired rule is not re-added without cause, and so the IDs that CHANGELOG.md, TESTS.md, the skills and the scripts cite still resolve. Format: `protocol/LEARNINGS-FORMAT.md`.

## Promoted

### L-019 · 2026-09-13 · On Windows `claude plugin eval` refuses any case that grants a shell tool, and repeated `--case` flags keep only the last one
- Trigger: the first full run of the plugin's suite (T-20260913-1): all 60 runs errored with "A shell tool (Bash or PowerShell) was granted but this machine cannot confine it (no sandbox backend on this platform)", even though `--allow-tools Bash` was passed; the rerun with `--case "trigger-*" --case "decoy-*" --case "outcome-*"` executed only outcome-1. On 2026-09-23 (2.1.280, T-20260923-2) `--case "trigger-[2-5]"` and `--case "trigger-{2,3,4,5}"` both answered "No eval cases found". Again on 2026-10-08 (T-20261008-1), with the entry active: `plugin eval --case trigger-12 --case trigger-13 --case decoy-7` ran only decoy-7, and `worth --ab --case action-5 --case outcome-3` ran only outcome-3, two reruns.
- Hypothesis: the harness sandboxes shell tools through a backend that exists only on Linux and macOS, and on Windows it fails closed rather than running unconfined; `--case` is a single-value option, so the last flag wins.
- Rule: `worth --case` now adds up repeated flags and accepts `a|b` (C-20261008-1), so prefer `worth --ab` for several cases; `claude plugin eval` still keeps only the last. On Windows, keep `allowed_tools` free of Bash and PowerShell in every harness case (trigger, decoy and outcome cases need only Read, Glob, Grep and Skill) and run action cases through the `evergreen-tester` agent, one fresh context per run; invoke the harness once per case-name pattern, written with `*` only (character classes and braces match nothing); pass `--judge-model sonnet` (the haiku judge failed a correct outcome-1 reply 3 of 3 votes); and delete the `%TEMP%\claude-eval-*` sandboxes afterwards, since `--keep-temp` and Windows both leave them behind. Since 2026-09-23 the owner's PC has WSL2 (Ubuntu with bubblewrap and socat), where the harness accepts shell grants and ran everlast's five cases with no refusal (everlast:T-20260923-4): run shell-granting cases there, in an invocation of their own, because `--allow-tools` is a global grant that a case's `allowed_tools` does not narrow (everlast:L-007).
- Evidence: `evals/results/full-run.json` (60 refused runs), `run2.json` (only outcome-1 executed), `run3-trigger.json` and `run3-decoy.json` (clean), the tester-agent reports for action-1 and action-2 (T-20260913-1); T-20260923-2 (trigger and decoy cases without a shell tool ran natively on Windows, sonnet judge).
- Scope: plugin (evergreen-test §Step 3, TESTING.md §6)
- Status: promoted: C-20261014-4 (TESTING.md §6 now carries the Windows shell refusal, the last `--case` winning, `*`-only patterns, the sonnet judge, WSL2 for shell cases and the temp-folder cleanup) · helpful 3 · harmful 0 · last_confirmed 2026-10-08

## Retired

### L-031 · 2026-10-01 · Value cases fail an A/B in ways no run reports; lint them before paying (`lint-cases-before-paid-runs`)
- Trigger: writing result-graded cases for obsidian-notes on 2026-10-01 hit five authoring traps, each of which would have spent runs measuring nothing: the outcome kind's default tools (Read, Glob, Grep, Write, 12 turns) cannot edit a file or run the skill's script, yet the case asked for a conversion; `redundant: true`, used to keep an answer-only case out of default runs, means "passed without the skill", so the static read reported mode 2 "already known" from a case never run; a file evidence `check` runs only when its `path` exists, so a checker that accepts README.md or INDEX.md behind `path: notes/INDEX.md` would fail a right answer; `regex on the answer:` was graded only in cases without `evidence`, forcing a second case with the same prompt; and a heredoc halved the regex backslashes, leaving an `evals.json` that did not parse, which `worth` read as "0 value cases" without saying why
- Hypothesis: the case format grew for `claude plugin eval` and the tester agent, and `--ab` reads some fields differently; nothing checked a suite against the runner before the money was spent
- Rule: run `worth --lite` until its case lint is clean, and `--heavy` refuses until it is; prove a checker on a hand-made correct copy, the skill's own output and the untouched fixture before any run; point a check's `path` at a file the fixture already has; give an outcome case that changes files `tools` and `max_turns`; never use `redundant` to hide a case. `--ab` now grades answer regexes together with the evidence and fills `<fixture>`-style placeholders from the case's `files`
- Evidence: `evergreen_worth.case_lint`, `evergreen_ab.case_prompt` and `grade_case`, tests `test_case_lint_finds_what_would_waste_an_ab` and `test_ab_harness_lessons_from_the_obsidian_notes_run`; obsidian-notes evals action-3 and outcome-2 with `evals/check_vault.py` (Ai/skill-worth-study/runs/obsidian-notes, owner's study folder)
- Scope: plugin (TESTING.md §8; evergreen-worth, evergreen-test)
- Status: retired 2026-10-14 · merged into L-030 in the consolidation pass C-20261014-4 · helpful 1 · harmful 0 · last_confirmed 2026-10-01

### L-029 · 2026-09-30 · A baseline note in evals.json is usually a prediction, not a run (`baseline-note-is-not-a-run`)
- Trigger: the skill worth study of 2026-09-30 read the value cases of 47 skills in 13 repositories; most `baseline` fields said "expected, not yet run", "filled by the first run" or an undated "without the skill a fresh session ...", and only package-modernize, wikiwright, everwrite, everlast, readwright and a few unity-agent and threewright cases had a dated run behind them. Many of the gains that were measured rested on a grader that requires the skill's own script (`cw.py`, `rw.py`, `tells.py`, `everlast.py`), which a baseline cannot pass whatever it produces
- Hypothesis: writing the expected baseline is cheap and feels like evidence, so it stands in for the run; and a process grader proves the route, not a better result
- Rule: count a baseline only when it is dated and says what the run did; treat undated predictions as never run; report value cases graded only on the unit's own scripts separately, and add at least one case graded on the result before calling a gain real
- Evidence: Ai/skill-worth-study/raw/prior-ab-evidence.md (owner's study folder); `evergreen_worth.baseline_status`, `process_only` and `evidence_gaps` with tests in `WorthUseful`. 2026-10-01: `process_only` treated every evidence leaf as an alternative, so obsidian-notes action-1 (a `vault_lint.py` trace `and` a file) counted as result-graded though no baseline can pass it; it now reads `and`, `all` and sequence steps as required and only `or` and `any` as alternatives. Same day: a dated partial pass ("without the skill 4 of 5 passed") read as a full pass and showed mode 2 "already known"; the first "N of M passed" now decides (C-20261001-2)
- Scope: plugin (TESTING.md §8; evergreen-worth, evergreen-test)
- Status: retired 2026-10-14 · the rule lives in evergreen-test SKILL.md Step 3 (a baseline is a dated run, never a prediction) and is enforced by `evergreen_worth.baseline_status`, `process_only` and `evidence_gaps` (C-20261001-2) (consolidation pass C-20261014-4) · helpful 2 · harmful 0 · last_confirmed 2026-10-01

### L-028 · 2026-09-30 · The plugin cache holds disabled plugins and old versions; overlap peers must come from enabled installs (`peers-from-enabled-plugins`)
- Trigger: `worth` warned that everscout-engage's description was close to `scout-ask`, a skill of a plugin that was installed but disabled; the peer glob read every folder under `plugins/cache`, every cached version included
- Hypothesis: the cache is a download store, not the listing; only `installed_plugins.json` entries enabled in `settings.json` reach the model
- Rule: build the peer set from enabled installs (`enabled_plugins()`), and fall back to the cache only when there is no registry
- Evidence: the false CHECK disappeared from the 47-skill triage after the change; test `test_peers_come_from_enabled_plugins_only`
- Scope: plugin (`evergreen_worth.peer_skill_files`)
- Status: retired 2026-10-14 · enforced by `evergreen_worth.enabled_plugins` and `peer_skill_files`, test `test_peers_come_from_enabled_plugins_only` (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-30

### L-027 · 2026-09-30 · `--setting-sources project` drops user skills, plugins and auto memory but still loads the user's CLAUDE.md; `--bare` needs an API key (`headless-arms-share-user-claude-md`)
- Trigger: a three-line probe from an empty temp folder (Claude Code 2.1.281, haiku): with `--setting-sources project` the skill listing held only built-ins and the model saw the user's global CLAUDE.md rule; with `--disable-slash-commands` the listing was empty; `--bare` answered "Not logged in" on an OAuth login
- Hypothesis: setting sources govern settings files, not CLAUDE.md discovery; `--bare` skips discovery but also OAuth
- Rule: run both A/B arms with `--setting-sources project` and record that the user's CLAUDE.md loads in both (fair, not blind); offer `--blind` (`--bare`) only when ANTHROPIC_API_KEY is set; never copy credentials into a temp config folder to get isolation
- Evidence: the probe outputs in this session; `evergreen_ab.isolation_args` and the `isolation` field of aggregate-result.json
- Scope: plugin (TESTING.md §6, §8; `scripts/evergreen_ab.py`)
- Status: retired 2026-10-14 · enforced by `evergreen_ab.isolation_args` (`--setting-sources project`, `--blind` only with an API key) and stated in TESTING.md §6 (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-30

### L-026 · 2026-09-30 · A `claude -p` child started from an IDE session logs the IDE's entrypoint; the temp working folder is what marks a test run (`headless-runs-log-ide-entrypoint`)
- Trigger: transcript usage counted 69 interactive wikiwright invocations; 61 were eval suites run with `claude -p` in `%TEMP%\ww9-suite-*` folders, every one logged with `entrypoint: claude-vscode` because the child inherits it from the VS Code session that started the suite
- Hypothesis: the entrypoint names the launcher's environment, not how the session is driven
- Rule: classify a session as headless when its entrypoint starts with `sdk` or its working folder is under the temp directory; harnesses should also pass `--no-session-persistence` so their runs leave no transcript to count
- Evidence: Ai/skill-worth-study/raw/usage-split-60d.json against the entrypoint-only count; test `test_transcript_uses_split_interactive_subagent_and_headless`
- Scope: plugin (`evergreen_worth.transcript_uses`)
- Status: retired 2026-10-14 · enforced by `evergreen_worth.transcript_uses` and stated in TESTING.md §8, test `test_transcript_uses_split_interactive_subagent_and_headless` (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-30

### L-025 · 2026-09-29 · Headless eval runs share the session's filesystem and write to the unit's source; end every suite with `git status` (`suite-ends-with-git-status`)
- Trigger: wikiwright's action suites ran through `claude -p` outside `claude plugin eval`'s throwaway workspace. In wikiwright:T-20260928-3 two skill-arm runs followed "capture learnings" and edited the source LEARNINGS.md, and one answered "does the wiki exist" with `git fetch` in a clone the launching session had made minutes before; in wikiwright:T-20260929-1 runs wrote a new learning, updates to three more and a line in a reference file, and left an untracked `package.json` (from `npm init -y`) in the skill's folder, which `git diff` does not show (2026-09-28, 2026-09-29)
- Hypothesis: a fresh context is not a fresh filesystem; a headless run or subagent has the same files, overlay and plugin paths as the session that starts it, so the unit's source and anything the session made before the suite are part of every case
- Rule: commit the unit's source before a suite and create nothing a case could see; end the suite with `git status --short` of the source, not only `git diff`; review each eval-written change (keep, renumber or reject, with the reason) before committing, and record it under side effects in the run's `T-` entry
- Evidence: wikiwright:L-017 (`evals-touch-the-source`), wikiwright:T-20260928-3 and wikiwright:T-20260929-1 (side-effects lines); wikiwright 0.5.0's `evals/run-suite.sh` ends with `git status --short` of the plugin source; TESTING.md §6
- Scope: plugin (TESTING.md §6; templates/MAINTENANCE.md.template §Tests)
- Status: retired 2026-10-14 · the rule lives in TESTING.md §6 (a fresh context is not a fresh filesystem; end with `git status --short`) and the MAINTENANCE template, since C-20260929-1 (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-29

### L-024 · 2026-09-23 · Any plugin-kind unit took over the registry's `plugin_root`
- Trigger: after a refresh of another plugin unit (`kind: plugin`) and the everlast release's `checked` runs on 2026-09-23, `registry.json` named that other plugin's folder as `plugin_root`, so pointer-mode units that follow MAINTENANCE.md's "Finding the plugin" looked for the protocol in the wrong folder
- Hypothesis: `register` treated `kind: plugin` as "this is the evergreen plugin", but every plugin that is itself an evergreen unit has that kind
- Rule: only a folder that holds `scripts/evergreen.py` and `protocol/PROTOCOL.md` may become `plugin_root`; after refreshing any plugin unit on an older version, check `plugin_root` in `registry.json`
- Evidence: the registry on the owner's machine pointed at the other plugin after its refresh; fixed in C-20260923-16 with a test
- Scope: global
- Status: retired 2026-10-14 · enforced by `register` since C-20260923-16 (only the folder with scripts/evergreen.py and protocol/PROTOCOL.md becomes `plugin_root`), test `test_register_sets_plugin_root_only_for_the_evergreen_plugin` (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-23

### L-023 · 2026-09-23 · Judge a decoy on what the agent did, not on the words it used
- Trigger: the first decoy run of 2026-09-23 under `claude plugin eval` (T-20260923-2): the Skill tool fired 0 times in all 9 runs with the plugin, yet the `llm` rubric ("does not route it to any evergreen plugin skill or mention refreshing, tuning or publishing an evergreen unit") failed 3 of them, replies that declined correctly but named `evergreen-test` as not fitting, or passed on the plugin's session-start question about contributing (in the harness's throwaway home the choice is always undecided, so that notice sits in every with-plugin run)
- Hypothesis: a rubric that forbids vocabulary instead of behaviour penalises the agent for explaining its choice, and a fresh install's session-start notices are part of every with-plugin run
- Rule: a decoy passes on the deterministic check (`tool_used: Skill`, `max: 0`, `arm: both`); an `llm` grader, if kept, judges whether the reply invoked or recommended the skill for the request, and says in so many words that naming a skill to decline it, or relaying a plugin notice, is fine
- Evidence: evals/cases/decoy-1, decoy-2 and decoy-3 `graders/outcome.md` (C-20260923-12); the rerun passed 9 of 9 with the plugin
- Scope: skill (evergreen-test; TESTING.md §7)
- Status: retired 2026-10-14 · the deterministic decoy shape lives in TESTING.md §6 (`tool: Skill`, `max: 0`, `arm: both`) and the llm wording in evals/cases/decoy-*/graders/outcome.md, since C-20260923-12 (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-23

### L-022 · 2026-09-23 · Parse `git status --porcelain` by its columns; the shared `git()` helper strips the first line's leading space
- Trigger: a publish commit on 2026-09-22 listed "Other files: - EARNINGS.md": `evergreen.py`'s `git()` returns stripped output, which removed the leading space of the first porcelain line (" M LEARNINGS.md"), and `changed_paths` cut a fixed three characters, so the first changed path lost its first letter in every commit message whose first change was an unstaged modification
- Hypothesis: stripping is right for one-line answers (a sha, a branch name) and wrong for column formats, where leading whitespace is data; it stayed unseen because only the commit body lists the paths, while `git add -A` staged the files correctly
- Rule: parse porcelain lines with a pattern over the status columns (`^([ MTADRCU?!]{1,2}) (.+)$`), never with a fixed slice of stripped output; keep the test that edits LEARNINGS.md first and checks the path comes back whole
- Evidence: C-20260923-11; test `GitTransport.test_changed_paths_keep_the_first_path_whole`
- Scope: skill
- Status: retired 2026-10-14 · enforced by the porcelain parser in evergreen_sync.py since C-20260923-11, test `GitTransport.test_changed_paths_keep_the_first_path_whole` (consolidation pass C-20261014-4) · helpful 0 · harmful 0 · last_confirmed 2026-09-23

### L-018 · 2026-09-10 · Base64 attachments through a mail connector cost about one token per character; a whole `changes.patch` overflows one tool call, and the Drive-picker route is cheaper
- Trigger: sending bundle 20260909-2229 through the Cowork Gmail connector: the 91 KB `changes.patch` became 121,352 base64 characters and the send call died with "Output token limit hit" before any message went out; a first attempt had already spent a subagent's session budget on pack, split and base64 prep. Claude in Chrome with "Insert files using Drive" then attached both `changes.patch` and the 235 KB mail archive from the outbox mirror in one message, with no base64 passing through the model.
- Hypothesis: L-013 sized the split by input capacity, but the binding limit is the per-call output ceiling of the model writing the tool call (base64 tokenizes at roughly one token per character); 24 KB pieces are about 33k characters and marginal, and the patch was never split at all.
- Rule: when Claude in Chrome (or any browser signed into the mailbox) is available, prefer the Drive-picker route: attach the mirrored bundle files as attachments in one message, then `notify --mark-sent <bundle> --via chrome-gmail`. Use the connector only for a bundle whose every attachment is under ~16 KB raw (about 21k base64 characters per call), splitting `changes.patch` the same way as the archive; never inline a whole patch or archive. Do the base64 prep in the same agent that sends, or not at all.
- Evidence: the failed connector attempt (agent report, 2026-09-10) and the successful Chrome send recorded in `EVERGREEN_HOME/notify.json` (via chrome-gmail).
- Scope: skill (evergreen-notify §Step 3)
- Status: retired 2026-10-14 · merged into L-013 in the consolidation pass C-20261014-4 · helpful 1 · harmful 0 · last_confirmed 2026-09-10

### L-015 · 2026-09-04 · A skill that says it did the thing is not evidence the thing happened; the protocol had no way to notice
- Trigger: the owner (2026-09-04): "I had one skill that was meant to delegate to another machine but it never did that"; the skill's runs read as successful delegations, and nothing in the paradigm (refresh, learnings, audit) would ever have flagged it, because all three read files and none run the skill
- Hypothesis: the paradigm treated "current" as "good"; a skill's main file can be right about the world and still be a narration, and the transcript of a narration is indistinguishable from the transcript of the action. Fake verification is the most reported agent hallucination in 2026 (R-20260904-4), so this was a class of failure, not one bad skill
- Rule: every skill carries an action case whose evidence is outside the transcript (a tool call in the trace, a file, a marker, a remote record); the core action step of a skill names the evidence it leaves and confirms it before reporting done; a failure report from a user goes to `evergreen-tune`, which reproduces in a fresh context and grades on evidence, never on the reply; run the suite after any edit to a skill
- Evidence: C-20260904-1; PROTOCOL §1 principle 5; TESTING.md §2
- Scope: skill
- Status: retired 2026-10-14 · the rule lives in PROTOCOL.md §1 principle 5 and §11 and TESTING.md §2, since C-20260904-1 (consolidation pass C-20261014-4) · helpful 0 · harmful 0 · last_confirmed 2026-09-04

### L-014 · 2026-09-03 · The synced mirror must carry what the recipient installs, not just what the trunk merges
- Trigger: the 0.4.0 bundle mirrored to `the synced Drive outbox folder\` held only UPDATE.md, changes.patch and manifest.json; the archive and install prompt stayed in the store, so the agent about to attach from Drive had the digest and no plugin. The mirror is exactly the route used when no transport works, which on this machine is every time
- Hypothesis: the mirror was written when a bundle was only a merge input; attaching the whole plugin came later (L-012) and the copy list was never revisited
- Rule: whatever `compose` attaches goes into the mirror as well; the mirror is a complete send, not a subset. When adding an attachment to an update email, check `copy_to_outbox_mirror` in the same edit
- Evidence: C-20260903-5
- Scope: plugin
- Status: retired 2026-10-14 · enforced by `evergreen_sync.copy_to_outbox_mirror`, which mirrors every composed attachment, since C-20260903-5 (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-012 · 2026-09-03 · An update email must be installable with one pasted prompt and one folder path
- Trigger: the owner (2026-09-03): "I didn't install the one at work because it had a lot of instructions"; the 0.2.0 update email listed six manual steps and pointed to the README
- Hypothesis: on a second machine the recipient is a person with an agent, not a reader; anything longer than "save these, paste this, give it the folder" is deferred and then forgotten
- Rule: every archive and every update email carries `INSTALL-PROMPT.txt` with exactly one placeholder (the folder the attachments were saved to); the agent does the joining, unzipping, marketplace, install, verification, and first audit. Install steps live in `templates/INSTALL-PROMPT.txt` only; README §Install describes the same flow for humans and keeps the by-hand route second
- Evidence: C-20260903-4
- Scope: plugin
- Status: retired 2026-10-14 · the rule lives in templates/INSTALL-PROMPT.txt and evergreen-pack SKILL.md (one placeholder, edit the template only), since C-20260903-4 (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-011 · 2026-09-03 · A merge input is hostile data: validate every path and fence off the config before anything is written
- Trigger: the 0.2.0 review fed `merge` a patch with `a/../pwned.txt`, `.git/hooks/post-checkout` and a hunk that changed `notify.to`; all three landed, and the merge skill tells agents to pull `[evergreen] update from` mails from Gmail, which anyone can send
- Hypothesis: the merge was written for the happy path (bundles the plugin itself built) and the email route widened the input set without widening the checks
- Rule: anything that reaches `merge` is untrusted; refuse paths outside the tree, `..`, `.git`; never apply patches to `evergreen.config.json`; gate code directories behind `--allow-code`; check the sender before merging mail; keep a hostile-patch test in the suite
- Evidence: C-20260903-3; test `Sync.test_hostile_patch_cannot_escape_or_change_config_or_code`
- Scope: skill
- Status: retired 2026-10-14 · enforced by `merge` since C-20260903-3, test `Sync.test_hostile_patch_cannot_escape_or_change_config_or_code` (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-010 · 2026-09-03 · Session-end hooks are too short to send mail; hand off to a detached process
- Trigger: designing the SessionEnd trigger (2026-09-03); the hooks reference says SessionEnd hooks share a 1.5 s budget, and Codex's SessionEnd is 1 to 3 s and always synchronous; an SMTP or Graph send takes longer than that
- Hypothesis: end-of-session hooks exist for cleanup notes, not for network work, and every agent that has one keeps it short so exits stay snappy
- Rule: a hook never does the work; it runs `notify --if-changed --detach`, which returns in milliseconds and leaves a `DETACHED_PROCESS` (Windows) or new-session (POSIX) child logging to `EVERGREEN_HOME/notify.log`; the same holds for Copilot and Codex hooks
- Evidence: R-20260903-1, R-20260903-4; C-20260903-1
- Scope: skill
- Status: retired 2026-10-14 · the hooks call `notify --if-changed --from-hook --detach` (scripts/evergreen-hook.sh, scripts/evergreen-hook.ps1) and PROTOCOL.md §10 (Publish) states the rule (consolidation pass C-20261014-4) · helpful 0 · harmful 0 · last_confirmed 2026-09-03

### L-009 · 2026-09-03 · A condensed protocol copy in every skill is a fan-out cost at each protocol change
- Trigger: the owner, while asking for the self-update email (2026-09-03): "when the evergreen is updated, most skills won't have to change ... They could point to the main install of the evergreen plugin"; at that point every converted skill carried a full MAINTENANCE.md copy of the protocol, so PROTOCOL §10 would have meant editing each one
- Hypothesis: the standalone mode was designed for portability to plugin-less machines and then used as the default everywhere, including machines that always have the plugin
- Rule: default to pointer mode (`protocol: "plugin"`, short MAINTENANCE.md that says where to look) for units outside the plugin; reserve the full copy for units that will travel without the plugin; keep the pointer file's fallback to the rules that never change (Step 0, hand rule)
- Evidence: C-20260903-2
- Scope: skill
- Status: retired 2026-10-14 · the rule lives in PROTOCOL.md §10 (pointer mode for units outside the plugin) and evergreen-convert SKILL.md (Mode), since C-20260903-2 (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-007 · 2026-09-02 · Gmail refuses a zip that contains .ps1 files
- Trigger: the owner could not send evergreen-0.1.1.zip through Gmail; the archive carries `scripts/pack.ps1` and `scripts/evergreen-hook.ps1`
- Hypothesis: Gmail's blocked-attachment list includes `.ps1` (and .bat, .cmd, .exe, .js, .vbs, .msi, .jar and more) and it scans inside zip, tar, and gz archives; renaming the zip does not help because the scan is by content
- Rule: for email use `pack --mail`, which stores blocked types as `name.ext.txt` and ships `unmail` instructions; keep the normal zip for Drive links and local transfer; never add a blocked type to the plugin without checking `MAIL_BLOCKED`
- Evidence: C-20260902-2; https://support.google.com/mail/answer/6590
- Scope: skill
- Status: retired 2026-10-14 · enforced by `pack --mail` and `MAIL_BLOCKED` in evergreen.py; evergreen-pack SKILL.md §Email says when to use it (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-02

### L-006 · 2026-09-02 · Cowork's plugin validator rejects angle brackets in a skill description
- Trigger: "Save plugin" on evergreen.plugin failed with "Skill 'skills/evergreen-pack': SKILL.md description cannot contain XML tags (x2)"; the description said `evergreen-<version>.zip`
- Hypothesis: the validator scans the frontmatter description for anything shaped like `<tag>` and treats a placeholder as markup; skill bodies are not checked the same way
- Rule: no `<...>` placeholders in any skill or agent frontmatter description; write "a versioned zip" or spell the value out. `evergreen.py lint` now flags this so it is caught before packing
- Evidence: C-20260902-1
- Scope: skill
- Status: retired 2026-10-14 · enforced by `evergreen.py lint`, which flags an angle-bracket placeholder in any frontmatter description (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-02

### L-004 · 2026-09-01 · A shipped config with a Windows path silently misbehaves on other hosts
- Trigger: `evergreen.config.json` held `D:\Evergreen`; on Linux `Path()` treated it as a relative directory and `init` would have created a folder literally named `D:\Evergreen` inside the mounted project
- Hypothesis: the plugin was written on one machine and the config was tested only there; portability was asserted, not exercised
- Rule: machine-specific config is keyed by `os.name` (or overridden by `EVERGREEN_HOME`), and a drive-letter path is rejected on non-Windows hosts with a fallback to `~/.evergreen`; run the test suite in a non-Windows sandbox before packaging
- Evidence: C-20260901-3; test `Home.test_windows_path_ignored_on_posix`
- Scope: skill
- Status: retired 2026-10-14 · enforced in code since C-20260901-3 (drive-letter homes ignored off Windows), test `Home.test_windows_path_ignored_on_posix` (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-01

### L-003 · 2026-09-01 · Paths inside a skill are relative to the file, but commands run from the user's project
- Trigger: independent review found every `python ../../scripts/evergreen.py` in the six skills would fail with "No such file" because the shell's cwd is the project, not the skill folder
- Hypothesis: markdown links and shell commands look alike in a SKILL.md, so the relative-link habit leaked into commands
- Rule: commands in skills use an absolute path built from the plugin root (`${CLAUDE_SKILL_DIR}/../..` in Claude Code, resolved from the skill's path elsewhere); markdown links may stay relative
- Evidence: C-20260901-3
- Scope: skill
- Status: retired 2026-10-14 · the rule lives in PROTOCOL.md §4 step 7 (absolute path from `${CLAUDE_SKILL_DIR}/../..`) and every shipped skill follows it (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-01

### L-002 · 2026-09-01 · Installed plugin copies are not the place to write state
- Trigger: while designing the Cowork install path, noted that Cowork copies plugins into its data folder and marks `save_skill` skills read-only; a refresh that wrote there would be lost on reinstall
- Hypothesis: install stores are caches; only the source folder persists across reinstalls
- Rule: every unit's `evergreen.json` carries `source`; Step 0 writes to `source` when the running copy differs from it, and the audit reports "reinstall needed" when the main file changed
- Evidence: PROTOCOL.md §3, PORTABILITY.md "Installed copies are read-only"; not yet confirmed by a live reinstall cycle
- Scope: skill
- Status: retired 2026-10-14 · the rule lives in PROTOCOL.md §3 (edits go to `source`, the audit flags "reinstall needed") and PORTABILITY.md "Installed copies are read-only" (consolidation pass C-20261014-4) · helpful 0 · harmful 0 · last_confirmed 2026-09-01

### L-001 · 2026-09-01 · Entry IDs must be dash-free dates or the link checker cannot see them
- Trigger: first scaffold test produced `R-2026-09-01-1` from a `{{DATE}}` placeholder; `evergreen.py links` reported the ID as referenced but never defined
- Hypothesis: the ID grammar (`R-YYYYMMDD-n`) was chosen for regex simplicity but the templates reused the human date placeholder
- Rule: IDs always use `{{DATEID}}` (YYYYMMDD) in templates and `YYYYMMDD` when written by hand; the human-readable date goes after the ID on the same title line
- Evidence: C-20260901-2
- Scope: skill
- Status: retired 2026-10-14 · the templates write IDs with `{{DATEID}}` (templates/CHANGELOG.md.template and siblings) and PROTOCOL.md §2 defines the dash-free grammar (consolidation pass C-20261014-4) · helpful 1 · harmful 0 · last_confirmed 2026-09-01
