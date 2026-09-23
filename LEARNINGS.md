# Learnings: evergreen

Procedural lessons about building and running the plugin, for [README.md](README.md) and the skills. Research findings live in [RESEARCH.md](RESEARCH.md); every change is logged in [CHANGELOG.md](CHANGELOG.md); test runs in [TESTS.md](TESTS.md); state in `evergreen.json`. Format and gate: `protocol/LEARNINGS-FORMAT.md`. Retired entries go to LEARNINGS-ARCHIVE.md with a reason.

Lessons about the owner's preferences or environments belong in `profile/`, not here.

## Active

### L-024 · 2026-09-23 · Any plugin-kind unit took over the registry's `plugin_root`
- Trigger: after a refresh of another plugin unit (`kind: plugin`) and the everlast release's `checked` runs on 2026-09-23, `registry.json` named that other plugin's folder as `plugin_root`, so pointer-mode units that follow MAINTENANCE.md's "Finding the plugin" looked for the protocol in the wrong folder
- Hypothesis: `register` treated `kind: plugin` as "this is the evergreen plugin", but every plugin that is itself an evergreen unit has that kind
- Rule: only a folder that holds `scripts/evergreen.py` and `protocol/PROTOCOL.md` may become `plugin_root`; after refreshing any plugin unit on an older version, check `plugin_root` in `registry.json`
- Evidence: the registry on the owner's machine pointed at the other plugin after its refresh; fixed in C-20260923-16 with a test
- Scope: global
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-23

### L-023 · 2026-09-23 · Judge a decoy on what the agent did, not on the words it used
- Trigger: the first decoy run of 2026-09-23 under `claude plugin eval` (T-20260923-2): the Skill tool fired 0 times in all 9 runs with the plugin, yet the `llm` rubric ("does not route it to any evergreen plugin skill or mention refreshing, tuning or publishing an evergreen unit") failed 3 of them, replies that declined correctly but named `evergreen-test` as not fitting, or passed on the plugin's session-start question about contributing (in the harness's throwaway home the choice is always undecided, so that notice sits in every with-plugin run)
- Hypothesis: a rubric that forbids vocabulary instead of behaviour penalises the agent for explaining its choice, and a fresh install's session-start notices are part of every with-plugin run
- Rule: a decoy passes on the deterministic check (`tool_used: Skill`, `max: 0`, `arm: both`); an `llm` grader, if kept, judges whether the reply invoked or recommended the skill for the request, and says in so many words that naming a skill to decline it, or relaying a plugin notice, is fine
- Evidence: evals/cases/decoy-1, decoy-2 and decoy-3 `graders/outcome.md` (C-20260923-12); the rerun passed 9 of 9 with the plugin
- Scope: skill (evergreen-test; TESTING.md §7)
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-23

### L-022 · 2026-09-23 · Parse `git status --porcelain` by its columns; the shared `git()` helper strips the first line's leading space
- Trigger: a publish commit on 2026-09-22 listed "Other files: - EARNINGS.md": `evergreen.py`'s `git()` returns stripped output, which removed the leading space of the first porcelain line (" M LEARNINGS.md"), and `changed_paths` cut a fixed three characters, so the first changed path lost its first letter in every commit message whose first change was an unstaged modification
- Hypothesis: stripping is right for one-line answers (a sha, a branch name) and wrong for column formats, where leading whitespace is data; it stayed unseen because only the commit body lists the paths, while `git add -A` staged the files correctly
- Rule: parse porcelain lines with a pattern over the status columns (`^([ MTADRCU?!]{1,2}) (.+)$`), never with a fixed slice of stripped output; keep the test that edits LEARNINGS.md first and checks the path comes back whole
- Evidence: C-20260923-11; test `GitTransport.test_changed_paths_keep_the_first_path_whole`
- Scope: skill
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-23

### L-021 · 2026-09-22 · Anchor a new CHANGELOG entry on the newest real heading, never on the first `### C-`
- Trigger: everlast-capture's CHANGELOG.md (2026-09-22 refresh) had its C-20260913-1 heading pasted into the middle of the `Entry shape:` line and the rest of that line stranded lower down as a fake `### C-YYYYMMDD-n` heading; the entries were also out of order
- Hypothesis: every companion's header quotes the entry template (`Entry shape: `### C-YYYYMMDD-n · ...``), so an insert-before-first-`### C-` (or `### R-`, `### L-`, `### T-`) lands inside that template line instead of above the newest entry
- Rule: when inserting an entry by text, anchor on the full heading of the current newest entry (`### C-20260918-1 ·`) or on a line that starts with `### C-` and is not inside the header; after writing, list the file's `### ` headings and the `Entry shape` line and check the order and that the template is intact
- Evidence: everlast/skills/everlast-capture/CHANGELOG.md repaired 2026-09-22 (Entry shape restored, stray heading removed, entries newest first); the same shape appears in every evergreen companion template
- Scope: global
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-22

### L-020 · 2026-09-17 · A shell hook committed from Windows can carry CRLF endings, and `* -text` in .gitattributes ships them everywhere
- Trigger: the privacy scrub of the tree for the public repository showed `scripts/evergreen-hook.sh` (and 40 other files) with CRLF endings; under `sh` on macOS or Linux a CRLF script fails at the first `case` line, so all three Claude Code hooks would have died silently on every non-Windows install, and nothing in the paradigm would have noticed because the development machine's Git Bash strips the `\r`. 2026-09-23: the scripts broke the rule themselves: `save_state`, `save_registry` and the scaffold wrote with `Path.write_text`, which translates `\n` to CRLF on Windows, so every `checked`, `bump`, `tested` or `init` there rewrote evergreen.json and new companions with CRLF (this release's own `checked` did it, and a publish commit on 2026-09-22 had rewritten all 90 lines of evergreen.json the same way)
- Hypothesis: editors and tools on Windows write CRLF by default; `* -text` (needed so pack manifests and patches hash the bytes on disk) also means git never normalises, so whatever a Windows editor wrote is what every clone gets
- Rule: keep every committed text file LF (`*.sh text eol=lf` on top of `* -text`, the whole tree normalised once), let `shipped_bytes` and `export` normalise `.sh` regardless, keep the test that asserts the hook has no `\r`, and let CI on a second operating system be the proof (C-20260917-2); an agent writing files on Windows passes `newline="\n"` or writes bytes, and so do the scripts (`write_lf` in evergreen.py writes bytes, because `Path.write_text(newline=)` is Python 3.10+)
- Evidence: C-20260917-2; the portability audit of 2026-09-17; test_sh_hook_is_lf_everywhere; C-20260923-13 and test_state_and_scaffold_files_are_written_lf
- Scope: global
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-17

### L-019 · 2026-09-13 · On Windows `claude plugin eval` refuses any case that grants a shell tool, and repeated `--case` flags keep only the last one
- Trigger: the first full run of the plugin's suite (T-20260913-1): all 60 runs errored with "A shell tool (Bash or PowerShell) was granted but this machine cannot confine it (no sandbox backend on this platform)", even though `--allow-tools Bash` was passed; the rerun with `--case "trigger-*" --case "decoy-*" --case "outcome-*"` executed only outcome-1. On 2026-09-23 (2.1.280, T-20260923-2) `--case "trigger-[2-5]"` and `--case "trigger-{2,3,4,5}"` both answered "No eval cases found".
- Hypothesis: the harness sandboxes shell tools through a backend that exists only on Linux and macOS, and on Windows it fails closed rather than running unconfined; `--case` is a single-value option, so the last flag wins.
- Rule: on Windows, keep `allowed_tools` free of Bash and PowerShell in every harness case (trigger, decoy and outcome cases need only Read, Glob, Grep and Skill) and run action cases through the `evergreen-tester` agent, one fresh context per run; invoke the harness once per case-name pattern, written with `*` only (character classes and braces match nothing); pass `--judge-model sonnet` (the haiku judge failed a correct outcome-1 reply 3 of 3 votes); and delete the `%TEMP%\claude-eval-*` sandboxes afterwards, since `--keep-temp` and Windows both leave them behind.
- Evidence: `evals/results/full-run.json` (60 refused runs), `run2.json` (only outcome-1 executed), `run3-trigger.json` and `run3-decoy.json` (clean), the tester-agent reports for action-1 and action-2 (T-20260913-1); T-20260923-2 (trigger and decoy cases without a shell tool ran natively on Windows, sonnet judge).
- Scope: plugin (evergreen-test §Step 3, TESTING.md §6)
- Status: active · helpful 2 · harmful 0 · last_confirmed 2026-09-23

### L-018 · 2026-09-10 · Base64 attachments through a mail connector cost about one token per character; a whole `changes.patch` overflows one tool call, and the Drive-picker route is cheaper
- Trigger: sending bundle 20260909-2229 through the Cowork Gmail connector: the 91 KB `changes.patch` became 121,352 base64 characters and the send call died with "Output token limit hit" before any message went out; a first attempt had already spent a subagent's session budget on pack, split and base64 prep. Claude in Chrome with "Insert files using Drive" then attached both `changes.patch` and the 235 KB mail archive from the outbox mirror in one message, with no base64 passing through the model.
- Hypothesis: L-013 sized the split by input capacity, but the binding limit is the per-call output ceiling of the model writing the tool call (base64 tokenizes at roughly one token per character); 24 KB pieces are about 33k characters and marginal, and the patch was never split at all.
- Rule: when Claude in Chrome (or any browser signed into the mailbox) is available, prefer the Drive-picker route: attach the mirrored bundle files as attachments in one message, then `notify --mark-sent <bundle> --via chrome-gmail`. Use the connector only for a bundle whose every attachment is under ~16 KB raw (about 21k base64 characters per call), splitting `changes.patch` the same way as the archive; never inline a whole patch or archive. Do the base64 prep in the same agent that sends, or not at all.
- Evidence: the failed connector attempt (agent report, 2026-09-10) and the successful Chrome send recorded in `EVERGREEN_HOME/notify.json` (via chrome-gmail).
- Scope: skill (evergreen-notify §Step 3)

### L-017 · 2026-09-10 · A documented feature can leave the docs without a changelog line; stamp doc-derived claims with the read date and re-check presence, not only changes
- Trigger: R-20260904-2 recorded `claude plugin eval`'s flags and graders from the plugins reference on 2026-09-04; the 2026-09-10 refresh found the whole section gone from the plugins reference, the CLI reference and `llms.txt`, with no changelog entry, while the unit still presented the flag list as current.
- Hypothesis: refresh queries look for what is new (changelog, releases, dated posts); a silent removal produces no such signal, so a withdrawn feature survives in a unit until someone tries to use it.
- Rule: when a claim comes from a doc page, keep the date it was read next to the claim; at every refresh, re-fetch the page behind each claim that names a command, flag or field and confirm it is still there (`llms.txt` or the page's own index is the quick proof); a claim that has vanished is downgraded in place ("documented on <date>, withdrawn by <date>"), not deleted, so the history stays readable.
- Evidence: R-20260910-1; TESTING.md §6 row rewritten with both dates.
- Scope: skill (evergreen-refresh); candidate line for agents/evergreen-researcher.md's subject track at its next edit

### L-016 · 2026-09-06 · `init --append-maintenance` skips the Maintenance section when SKILL.md already mentions evergreen.json
- Trigger: while scaffolding the five unity-agent skills (2026-09-06) each SKILL.md was written first with the template's Step 0 paragraph; `init --append-maintenance` then printed "SKILL.md already references evergreen.json; nothing appended", so the `## Maintenance` section (tier, interval, next due, file links) had to be added by hand to all five.
- Hypothesis: the guard treats any mention of evergreen.json as proof the whole maintenance block exists, but the template's Step 0 and the Maintenance section are separate pieces.
- Rule: when writing SKILL.md before `init`, include both the Step 0 paragraph and the `## Maintenance` section from `templates/MAINTENANCE-SECTION.md.template` yourself, or run `init` first on an empty folder and fill the body afterwards; do not rely on `--append-maintenance` to finish a pre-written file.
- Evidence: five manual appends on 2026-09-06 (unity-agent suite); `EG lint` passed afterwards.
- Scope: skill (evergreen-new)
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-06

### L-015 · 2026-09-04 · A skill that says it did the thing is not evidence the thing happened; the protocol had no way to notice
- Trigger: the owner (2026-09-04): "I had one skill that was meant to delegate to another machine but it never did that"; the skill's runs read as successful delegations, and nothing in the paradigm (refresh, learnings, audit) would ever have flagged it, because all three read files and none run the skill
- Hypothesis: the paradigm treated "current" as "good"; a skill's main file can be right about the world and still be a narration, and the transcript of a narration is indistinguishable from the transcript of the action. Fake verification is the most reported agent hallucination in 2026 (R-20260904-4), so this was a class of failure, not one bad skill
- Rule: every skill carries an action case whose evidence is outside the transcript (a tool call in the trace, a file, a marker, a remote record); the core action step of a skill names the evidence it leaves and confirms it before reporting done; a failure report from a user goes to `evergreen-tune`, which reproduces in a fresh context and grades on evidence, never on the reply; run the suite after any edit to a skill
- Evidence: C-20260904-1; PROTOCOL §1 principle 5; TESTING.md §2
- Scope: skill
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-04

### L-014 · 2026-09-03 · The synced mirror must carry what the recipient installs, not just what the trunk merges
- Trigger: the 0.4.0 bundle mirrored to `the synced Drive outbox folder\` held only UPDATE.md, changes.patch and manifest.json; the archive and install prompt stayed in the store, so the agent about to attach from Drive had the digest and no plugin. The mirror is exactly the route used when no transport works, which on this machine is every time
- Hypothesis: the mirror was written when a bundle was only a merge input; attaching the whole plugin came later (L-012) and the copy list was never revisited
- Rule: whatever `compose` attaches goes into the mirror as well; the mirror is a complete send, not a subset. When adding an attachment to an update email, check `copy_to_outbox_mirror` in the same edit
- Evidence: C-20260903-5
- Scope: plugin
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-013 · 2026-09-03 · A mail connector carries attachments as base64 through the model; split anything over a few dozen KB
- Trigger: sending the 0.2.0 archive to the work address through Claude Code's Gmail MCP (2026-09-03): the 150 KB mail zip is 200 KB of base64, about 190k tokens in one tool call, so it could not be attached; only `plugin.json` and `INSTALL.txt` went; the Drive connector was a different Google account than the desktop mirror, Outlook had no COM, no SMTP secret existed
- Hypothesis: connector attachments are tool-call arguments, so their ceiling is the model's output budget, not Gmail's 25 MB
- Rule: through a connector, send the archive as `pack --mail --split 24` pieces, one per message in the same thread, each read from disk; put the body and the patch on the first message; never base64 the whole archive in one call. Prefer the script's own transports (smtp, graph, outlook) when one is set up
- Evidence: C-20260903-4; skills/evergreen-notify §Step 3
- Scope: plugin
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-012 · 2026-09-03 · An update email must be installable with one pasted prompt and one folder path
- Trigger: the owner (2026-09-03): "I didn't install the one at work because it had a lot of instructions"; the 0.2.0 update email listed six manual steps and pointed to the README
- Hypothesis: on a second machine the recipient is a person with an agent, not a reader; anything longer than "save these, paste this, give it the folder" is deferred and then forgotten
- Rule: every archive and every update email carries `INSTALL-PROMPT.txt` with exactly one placeholder (the folder the attachments were saved to); the agent does the joining, unzipping, marketplace, install, verification, and first audit. Install steps live in `templates/INSTALL-PROMPT.txt` only; README §Install describes the same flow for humans and keeps the by-hand route second
- Evidence: C-20260903-4
- Scope: plugin
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-009 · 2026-09-03 · A condensed protocol copy in every skill is a fan-out cost at each protocol change
- Trigger: the owner, while asking for the self-update email (2026-09-03): "when the evergreen is updated, most skills won't have to change ... They could point to the main install of the evergreen plugin"; at that point every converted skill carried a full MAINTENANCE.md copy of the protocol, so PROTOCOL §10 would have meant editing each one
- Hypothesis: the standalone mode was designed for portability to plugin-less machines and then used as the default everywhere, including machines that always have the plugin
- Rule: default to pointer mode (`protocol: "plugin"`, short MAINTENANCE.md that says where to look) for units outside the plugin; reserve the full copy for units that will travel without the plugin; keep the pointer file's fallback to the rules that never change (Step 0, hand rule)
- Evidence: C-20260903-2
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-010 · 2026-09-03 · Session-end hooks are too short to send mail; hand off to a detached process
- Trigger: designing the SessionEnd trigger (2026-09-03); the hooks reference says SessionEnd hooks share a 1.5 s budget, and Codex's SessionEnd is 1 to 3 s and always synchronous; an SMTP or Graph send takes longer than that
- Hypothesis: end-of-session hooks exist for cleanup notes, not for network work, and every agent that has one keeps it short so exits stay snappy
- Rule: a hook never does the work; it runs `notify --if-changed --detach`, which returns in milliseconds and leaves a `DETACHED_PROCESS` (Windows) or new-session (POSIX) child logging to `EVERGREEN_HOME/notify.log`; the same holds for Copilot and Codex hooks
- Evidence: R-20260903-1, R-20260903-4; C-20260903-1
- Scope: skill
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-03

### L-011 · 2026-09-03 · A merge input is hostile data: validate every path and fence off the config before anything is written
- Trigger: the 0.2.0 review fed `merge` a patch with `a/../pwned.txt`, `.git/hooks/post-checkout` and a hunk that changed `notify.to`; all three landed, and the merge skill tells agents to pull `[evergreen] update from` mails from Gmail, which anyone can send
- Hypothesis: the merge was written for the happy path (bundles the plugin itself built) and the email route widened the input set without widening the checks
- Rule: anything that reaches `merge` is untrusted; refuse paths outside the tree, `..`, `.git`; never apply patches to `evergreen.config.json`; gate code directories behind `--allow-code`; check the sender before merging mail; keep a hostile-patch test in the suite
- Evidence: C-20260903-3; test `Sync.test_hostile_patch_cannot_escape_or_change_config_or_code`
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-03

### L-001 · 2026-09-01 · Entry IDs must be dash-free dates or the link checker cannot see them
- Trigger: first scaffold test produced `R-2026-09-01-1` from a `{{DATE}}` placeholder; `evergreen.py links` reported the ID as referenced but never defined
- Hypothesis: the ID grammar (`R-YYYYMMDD-n`) was chosen for regex simplicity but the templates reused the human date placeholder
- Rule: IDs always use `{{DATEID}}` (YYYYMMDD) in templates and `YYYYMMDD` when written by hand; the human-readable date goes after the ID on the same title line
- Evidence: C-20260901-2
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-01

### L-002 · 2026-09-01 · Installed plugin copies are not the place to write state
- Trigger: while designing the Cowork install path, noted that Cowork copies plugins into its data folder and marks `save_skill` skills read-only; a refresh that wrote there would be lost on reinstall
- Hypothesis: install stores are caches; only the source folder persists across reinstalls
- Rule: every unit's `evergreen.json` carries `source`; Step 0 writes to `source` when the running copy differs from it, and the audit reports "reinstall needed" when the main file changed
- Evidence: PROTOCOL.md §3, PORTABILITY.md "Installed copies are read-only"; not yet confirmed by a live reinstall cycle
- Scope: skill
- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-01

### L-003 · 2026-09-01 · Paths inside a skill are relative to the file, but commands run from the user's project
- Trigger: independent review found every `python ../../scripts/evergreen.py` in the six skills would fail with "No such file" because the shell's cwd is the project, not the skill folder
- Hypothesis: markdown links and shell commands look alike in a SKILL.md, so the relative-link habit leaked into commands
- Rule: commands in skills use an absolute path built from the plugin root (`${CLAUDE_SKILL_DIR}/../..` in Claude Code, resolved from the skill's path elsewhere); markdown links may stay relative
- Evidence: C-20260901-3
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-01

### L-004 · 2026-09-01 · A shipped config with a Windows path silently misbehaves on other hosts
- Trigger: `evergreen.config.json` held `D:\Evergreen`; on Linux `Path()` treated it as a relative directory and `init` would have created a folder literally named `D:\Evergreen` inside the mounted project
- Hypothesis: the plugin was written on one machine and the config was tested only there; portability was asserted, not exercised
- Rule: machine-specific config is keyed by `os.name` (or overridden by `EVERGREEN_HOME`), and a drive-letter path is rejected on non-Windows hosts with a fallback to `~/.evergreen`; run the test suite in a non-Windows sandbox before packaging
- Evidence: C-20260901-3; test `Home.test_windows_path_ignored_on_posix`
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-01

### L-007 · 2026-09-02 · Gmail refuses a zip that contains .ps1 files
- Trigger: the owner could not send evergreen-0.1.1.zip through Gmail; the archive carries `scripts/pack.ps1` and `scripts/evergreen-hook.ps1`
- Hypothesis: Gmail's blocked-attachment list includes `.ps1` (and .bat, .cmd, .exe, .js, .vbs, .msi, .jar and more) and it scans inside zip, tar, and gz archives; renaming the zip does not help because the scan is by content
- Rule: for email use `pack --mail`, which stores blocked types as `name.ext.txt` and ships `unmail` instructions; keep the normal zip for Drive links and local transfer; never add a blocked type to the plugin without checking `MAIL_BLOCKED`
- Evidence: C-20260902-2; https://support.google.com/mail/answer/6590
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-02

### L-006 · 2026-09-02 · Cowork's plugin validator rejects angle brackets in a skill description
- Trigger: "Save plugin" on evergreen.plugin failed with "Skill 'skills/evergreen-pack': SKILL.md description cannot contain XML tags (x2)"; the description said `evergreen-<version>.zip`
- Hypothesis: the validator scans the frontmatter description for anything shaped like `<tag>` and treats a placeholder as markup; skill bodies are not checked the same way
- Rule: no `<...>` placeholders in any skill or agent frontmatter description; write "a versioned zip" or spell the value out. `evergreen.py lint` now flags this so it is caught before packing
- Evidence: C-20260902-1
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-02

### L-005 · 2026-09-01 · The paradigm's own skills must obey the paradigm, and a reviewer is how you find out they do not
- Trigger: the six shipped skills had a Maintenance footer but no Step 0 freshness check, the exact mechanism the protocol says runs "every use"; the plugin could not notice its own staleness where hooks do not run
- Hypothesis: the template was written after the first skills and never applied back to them
- Rule: after changing a template or protocol rule, re-read every shipped unit against it (or run `audit --checks`), and get one independent review before packaging a version
- Evidence: C-20260901-3
- Scope: skill
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-01

### L-008 · 2026-09-02 · A Cowork save_skill skill with no source folder can use its own data folder as the evergreen unit
- Trigger: converting science-study-evaluator (2026-09-02); the only copy of SKILL.md was the read-only Cowork store, and the skill already kept a hand-rolled state.json plus a methodology file under `D:\Evergreen\science-study-evaluator`
- Hypothesis: the writable folder the skill already reads at run time is the natural source; putting SKILL.md and the companions there means a research refresh edits the checklist without re-saving the skill, and only SKILL.md edits need `save_skill overwrite`
- Rule: for a save_skill skill, set the unit dir and `source` to the skill's existing data folder (create one if none); write SKILL.md there with frontmatter, run `init --standalone` without `--append-maintenance` when the SKILL.md already carries its own Step 0 (the script skips the append once "evergreen.json" appears in the file), then pass the body without frontmatter to `save_skill` (name and description go in as parameters). Step 0 in such a skill must use the absolute unit path, since the installed copy has no evergreen.json beside it
- Evidence: D:\Evergreen\science-study-evaluator (links OK, lint OK, registered 2026-09-02); skill re-saved and listed with the new description
- Scope: env:home-pc-cowork
- Status: active · helpful 1 · harmful 0 · last_confirmed 2026-09-02
