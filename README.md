# Evergreen

Self-maintaining, self-proving skills and knowledge for AI agents. An evergreen unit (a skill, a doc, a codemap, a preferences profile) re-researches its topic from primary sources on an adaptive schedule, writes down what it learns so nobody teaches the agent the same thing twice, logs every change with its reason, keeps a map of any codebase it explores, and, for skills, carries the tests that prove it triggers, acts, and gets the result right, with a tuning loop for when it does not. It works in Claude Code, Cowork, and any agent that reads markdown (Copilot, Codex, Cursor, Gemini CLI), because the whole paradigm is plain files plus one small JSON state file. Scripts are conveniences, not requirements.

This plugin is its own first unit: see [RESEARCH.md](RESEARCH.md) for the evidence behind the design, [CHANGELOG.md](CHANGELOG.md) for what changed and why, [LEARNINGS.md](LEARNINGS.md) for lessons, and `evergreen.json` for its schedule (tier `fast`, checked every couple of weeks).

## What you get

| Piece | What it does |
|---|---|
| `templates/INSTALL-PROMPT-GIT.txt` | The one-paste install prompt: the agent clones (or pulls) the repository, registers the marketplace, installs. `INSTALL-PROMPT.txt` is the archive form, shipped in every pack and update email. |
| `protocol/` | The paradigm. `PROTOCOL.md` is the spec; `INTERVALS.md` the refresh math; `TESTING.md` how a skill is proven and tuned; `LEARNINGS-FORMAT.md`, `CODEMAP-FORMAT.md`, `PORTABILITY.md` the details. |
| `skills/evergreen-refresh` | Re-research a due unit on four tracks, apply delta edits, re-test if the skill changed, reschedule. |
| `skills/evergreen-learn` | Capture a correction, repeated error, workaround, environment fact, preference, or failed test into the right file. |
| `skills/evergreen-map` | Build and update the plugin's own codemap of any repo you explore. |
| `skills/evergreen-convert` | Make an existing skill or doc evergreen without rewriting it; skills get a test suite scaffolded. |
| `skills/evergreen-new` | Create new skills evergreen by default, handed over only with a run suite. |
| `skills/evergreen-test` | Write and run a skill's eval suite: trigger prompts and decoys, action cases proven by evidence outside the transcript, outcome cases, baseline without the skill. |
| `skills/evergreen-tune` | Fix a skill that failed a test or failed in use: reproduce, classify, learn, research if stale, smallest edit, re-run. Three iterations, then report. |
| `skills/evergreen-audit` | Table of every unit: staleness, drift, test status, links, budgets. Run after install. |
| `skills/evergreen-publish` | Push the plugin's self-changes to the trunk repository: straight to `master` from a maintainer's clone, an update branch plus a pull request from anyone else's; `pull` brings a clone up to date. |
| `skills/evergreen-merge` | Review and land what other clones published: merge pull requests on the host, resolve the rare conflict with the delta-edit rule, then pull and reinstall. Also folds an email bundle for the fallback route. |
| `skills/evergreen-pack` | One archive for Cowork (`.plugin`), a backup, a share copy for someone without repository access, or an export into a repo's `.agents/`. |
| `skills/evergreen-diff` | What this clone changed and has not yet published: digest plus unified diff against its baseline. |
| `skills/evergreen-notify` | The email fallback for a machine that cannot reach the repository: bundle, transport ladder (Outlook, Graph, Gmail SMTP, a mail connector, Chrome), outbox. |
| `agents/` | `evergreen-researcher` (research pass in its own context), `evergreen-mapper` (repo sweep), `evergreen-tester` (one eval case in a fresh context, strict trace report). |
| `scripts/evergreen.py` | State, scheduling, scaffolding, audit, link and lint checks, test records (`test-init`, `tested`, `failed`), the use log (`use-log`, `uses`), export, pack. Stdlib only. `evergreen_sync.py` adds publish, pull, where, baseline, diff, and the email fallback (notify, merge). `test_evergreen.py` covers the math, the tests layer and the sync. `pack.ps1` packages without Python. |
| `templates/` | Companion-file templates (including `TESTS.md` and `evals.json`), the pointer and standalone `MAINTENANCE.md` forms, and snippets for `AGENTS.md`, `CLAUDE.md`, `copilot-instructions.md`. |
| `profile/` | Portable preferences (`AI-PREFERENCES.md`) and environment facts (`ENVIRONMENTS.md`). Learnings-driven, no web research. |
| `hooks/` | Claude Code hooks: `SessionStart` prints due units into context (silent when nothing is due); `SessionEnd` publishes any self-update to the trunk repository in a detached process; `PostToolUse` on the `Skill` tool writes the use log. |
| `evals/`, `TESTS.md` | The plugin's own suite and run log; every skill unit carries the same pair. |

## How a unit behaves

1. Every use starts with one small read of `evergreen.json`. Below the due date, nothing else happens.
2. Past the due date (or when a learning has flagged a contradiction), the unit says so in one line, finishes the user's task, then refreshes in the same session: a few scoped searches of primary sources, findings logged with magnitudes, the main file edited in place, the change logged with its reason, the suite re-run if a skill changed. Every refresh covers four tracks: the subject (the goal and the latest thinking on reaching it), the tooling built for it (skills, plugins, MCP servers, scripts, knowledge graphs, ranked by real use rather than by listicle), how other people are using agents on the same goal, and how they test that the job was done. A maintained, well-used tool that does what the skill's own procedure does counts as a superseded claim, the same as a fact going wrong.
3. The next interval adapts: divide by 4 on a major change, by 2 on a real change, hold on cosmetic churn, multiply by 1.5 when nothing changed, all inside the tier's bounds. Topics can be promoted or demoted between tiers, capped by known upcoming events, or switched to "verify at use" when too volatile to schedule.
4. Whenever the user corrects the agent, the same error repeats, or a fact about the environment turns up, a learning is written immediately with its trigger and hypothesis, gated against duplicates, and later promoted into the main file or retired with a reason.
5. Any repo explored gets a codemap in the plugin's store, stamped with the git sha, every claim marked verified or inferred, and a log of which questions it has answered. The map says, every time, that it may be stale, incomplete, or confused.
6. When the plugin changes itself, wherever it is installed, it commits the change with a subject naming the new entries and pushes it to the trunk repository: straight to `master` when the clone is a maintainer's, as an update branch and a pull request when it is anyone else's. The owner merges pull requests on the host; every other clone pulls. One repository, fixed in config; nothing is ever force-pushed; email remains the fallback for a machine that cannot reach it.
7. Every skill carries a suite (`evals/evals.json`, skill-creator's format plus evergreen fields) with trigger prompts and decoys, action cases that pass only on evidence outside the transcript (a tool call in the trace, a file, a marker, a remote record; never the reply saying "done"), outcome cases, and a baseline of what a fresh context does without the skill. Runs are logged in `TESTS.md`; a failing case is a Step 0 signal like a contradiction. When a case fails, or the skill fails in use, the tuning loop reproduces it in a fresh context, classifies it (undertrigger, overtrigger, no-op, fallback, wrong-outcome, environment, harness), writes the learning, researches the subject's own testing and tooling when the unit's research is older than half its interval (always for no-op and fallback), makes the smallest edit for the class, and re-runs; three iterations, then it reports what it tried.

## Install

Prerequisites: git, Python 3.9+ (`python` on Windows, `python3` on macOS and Linux; on macOS that means the Xcode Command Line Tools or a python.org install), and `gh` for pull requests. Nothing else: the scripts are stdlib only and the hooks are POSIX `sh`, which Claude Code on Windows runs through Git Bash.

**From the repository (the normal way).** Open Claude Code and paste `templates/INSTALL-PROMPT-GIT.txt` (the repository URL is already in it). The agent clones the repository under a local marketplace root (`~/claude-plugins` unless one already exists), or pulls if the clone is there, registers the marketplace, installs or reinstalls with `claude plugin`, verifies with `claude plugin list`, and runs `where` and the first audit. Updating later is `python <clone>/scripts/evergreen.py pull` followed by a reinstall when it says skills or scripts changed. The repository is public (https://github.com/m4bwav/evergreen-protocol); cloning needs no account, and `gh auth login` once lets the clone open pull requests with its improvements.

**From an update email or a packed archive (fallback).** Save the attachments to one folder and paste the archive form of the prompt (`INSTALL-PROMPT.txt`, inside every archive and at the top of every update email), replacing its one placeholder with that folder's path. An archive install is not a git clone, so it reports by email until it is replaced by a clone.

**By hand (Claude Code).** `claude plugin install` takes a marketplace entry, not a bare path, so give it one: put the plugin folder under some ROOT, write `ROOT/.claude-plugin/marketplace.json` as `{"name": "mark-local", "owner": {"name": "..."}, "plugins": [{"name": "evergreen", "source": "./evergreen"}]}`, then:

```
claude plugin marketplace add ROOT
claude plugin install evergreen@mark-local --scope user
claude plugin list
```

Claude Code caches a copy; after changing the source (an edit, or a `pull` that touched skills or scripts), `claude plugin marketplace update mark-local`, then uninstall and install again (a same-version `update` does not recopy). The manifest's `agents` is a list of files and `hooks/hooks.json` is picked up on its own (naming it in the manifest is a duplicate-hooks error). The `SessionStart` hook runs `scripts/evergreen-hook.sh` (Claude Code on Windows ships with Git Bash, so `sh` is there); if hooks on your machine go through PowerShell, point one at `scripts/evergreen-hook.ps1` instead (example in that file). The hook prints nothing when nothing is due.

Then run the `evergreen-audit` skill once in a new session: it confirms the store, creates the registry, and refreshes the plugin's own research if it sat unused.

Cowork (desktop): install the `evergreen.plugin` file produced by `evergreen-pack` (or `python scripts/evergreen.py pack`), or add the folder through Customize. Cowork keeps a copy; edits made by refreshes go to the `source` path recorded in `evergreen.json`, and the audit tells you when to reinstall. Cowork's sandbox cannot see host paths outside the selected folder, so the store and the script run through Desktop Commander there, or the protocol is followed by hand.

Other agents (Copilot, Codex, Cursor, Gemini CLI, Windsurf): `python scripts/evergreen.py export /path/to/repo` copies the plugin into `<repo>/.agents/` with its layout intact (skills at `.agents/skills/evergreen-*`, protocol and scripts beside them, so every relative link still resolves). Then paste `templates/AGENTS.md.snippet` into the repo's `AGENTS.md`, and add `templates/CLAUDE.md.snippet` as `CLAUDE.md` so Claude Code sees the same rules. Gemini CLI needs `.gemini/settings.json` → `{"context": {"fileName": "AGENTS.md"}}`.

Store location: set `EVERGREEN_HOME` (environment variable) or `evergreen.config.json` at the plugin root, which takes a string or a per-OS map (`{"home": {"nt": "D:\\Evergreen", "posix": "~/.evergreen"}}`). Default is `~/.evergreen`. A Windows drive-letter path is ignored on Mac and Linux rather than creating a stray folder. The store holds the registry, codemaps, and units that have no other home.

## Using the scripts

```
python scripts/evergreen.py audit --checks          # everything, with link and lint problems
python scripts/evergreen.py status <unit>           # one line
python scripts/evergreen.py next <unit> --m 0.4     # dry-run the interval rule
python scripts/evergreen.py checked <unit> --m 0.4 --note "what changed"
python scripts/evergreen.py init <dir> --name x --topic "..." --tier moderate --append-maintenance [--standalone]
python scripts/evergreen.py map-init <repo>         # codemap unit in the store
python scripts/evergreen.py drift <map> [--update-sha]
python scripts/evergreen.py links <unit>  |  lint <unit>  |  flag <unit> --contradiction "why"
python scripts/evergreen.py test-init <unit>       # add evals/evals.json, TESTS.md and the tests block to an existing skill
python scripts/evergreen.py tested <unit> --passed 5 --failed 1 --failing action-1 --harness tester --note "..."
python scripts/evergreen.py failed <unit> --case action-1 --class no-op --note "..."   # failure in use; says whether research comes first
python scripts/evergreen.py uses [--skill x] [--days 7]   # recent skill invocations from the use log (Claude Code hook)
python scripts/evergreen.py export <repo>          # copy into <repo>/.agents/ for other agents
python scripts/evergreen.py pack [--out <dir>]     # evergreen-<version>.zip + evergreen.plugin
python scripts/evergreen.py pack --mail            # Gmail-safe zip (scripts stored as .txt); unmail <dir> restores
python scripts/evergreen.py pack --share [--mail]  # copy for someone else: no profile/, no address in the config
python scripts/evergreen.py where                  # root, store, env name, baseline, git remote/role/ahead/behind, last publish, notify readiness
python scripts/evergreen.py publish [--dry-run] [--branch] [--message "..."]   # commit + push to master (maintainer) or branch + PR; runs by itself after checked/bump/tested and at session end
python scripts/evergreen.py pull [--dry-run]       # fast-forward this clone from the trunk; says when a reinstall is due
python scripts/evergreen.py baseline [--from <pack zip>]   # snapshot this install as the base for diff
python scripts/evergreen.py diff                   # what this clone has not published yet (UPDATE.md, changes.patch, manifest.json)
python scripts/evergreen.py notify [--if-changed] [--dry-run] [--transport smtp]   # git: same as publish; email route when update.transport is email
python scripts/evergreen.py merge <bundle | changes.patch | saved-email.txt> [--dry-run]   # email route: fold a bundle into the trunk
python scripts/test_evergreen.py                    # self-test
```

Run the script by absolute path; the shell's working directory is usually your project, not the plugin. Every command fails soft (prints a note, exits 0) unless `--strict` follows the subcommand, so hooks never break a session.

## Making things evergreen

- An existing skill: say "make X self-maintaining" (`evergreen-convert`). It adds the companions, migrates any hand-rolled refresh state, appends the Step 0 and Maintenance sections, and registers the unit. Skills outside the plugin point at it (`protocol: "plugin"`, a short `MAINTENANCE.md` that says where to look), so a protocol update never means editing every skill; only skills that travel to machines without the plugin get the full self-contained copy.
- A new skill: just ask for a skill; `evergreen-new` makes it evergreen unless you say "plain skill", and hands it over with its suite run.
- A skill that misbehaves: say what it did not do ("the delegation skill never delegated"); `evergreen-tune` reproduces it in a fresh context, classifies the failure, researches the subject's testing and tooling if the unit is stale, fixes, and re-runs. "Test this skill" or "prove X works" runs `evergreen-test`.
- A repo: paste the `AGENTS.md` snippet; docs and codemaps in `docs/` can carry their own `evergreen.json` and `MAINTENANCE.md`.
- A knowledge doc: `evergreen.py init <dir> --kind doc --main <file>.md ...`.

## Design notes

Five principles settle most edge cases: research beats recall on anything time-sensitive (model knowledge is a stale snapshot on fast-moving topics); lazy and never blocking (staleness is checked on use, the task comes first); delta edits, never wholesale rewrites; subject and ecosystem both, since a skill can be right about the world and wrong about the tools; evidence, not claims, since a skill that narrates an action reads exactly like one that performed it. The evidence for each, and for the interval math, the learnings format, the testing rules, and the codemap rules, is in RESEARCH.md with sources.

## Testing

Why a separate pillar: refresh keeps a skill current, and a current skill can still fail in three quiet ways. It does not trigger on the user's phrasing (the most common failure in 2026 evals). It triggers and narrates the action without performing it, which the transcript cannot distinguish from success. Or the tool it depends on moved, and it falls back to another route. `protocol/TESTING.md` covers the case kinds, the evidence rule, the harness per environment (skill-creator's runner, the `evergreen-tester` agent, a headless CLI, `claude plugin eval` where that undocumented command runs, promptfoo and friends as options), how a suite is judged (three runs per case, with-versus-without), and the bounded tuning loop with its research gate. The suite format is skill-creator's `evals/evals.json` plus a few fields, so its runner and description improver work on the same file. Budgets keep files short: main files under 200 lines, active learnings under 200, codemaps under 150; overflow is archived, not deleted, so the reasoning lineage survives.

## Packaging

A clone is the normal install; packing is for Cowork's `.plugin`, a backup, and share copies. `python scripts/evergreen.py pack` (or the `evergreen-pack` skill) writes two files next to the plugin folder: `evergreen-<version>.zip`, which unzips to an `evergreen/` folder plus `INSTALL.txt` and is the thing to back up or carry to another machine, and `evergreen.plugin`, the same files flat, which is what Cowork's "Save plugin" button installs (Claude Code installs from the folder and never needs it). Python's built-in zip does the work; nothing to install, and both open in 7-Zip, Explorer, or Finder. No Python? `scripts/pack.ps1` does the same with 7-Zip if present or Windows' built-in `Compress-Archive`.

Emailing it: Gmail rejects `.ps1` and other script types even inside a zip, so `python scripts/evergreen.py pack --mail` writes `evergreen-<version>-mail.zip` with those files stored as `name.ps1.txt`. After unzipping, `python evergreen/scripts/evergreen.py unmail evergreen` renames them back (INSTALL.txt inside says so). Or attach the normal zip via Google Drive instead.

Every archive also carries `INSTALL-PROMPT.txt`, and `pack` writes a copy beside it as `evergreen-<version>-INSTALL-PROMPT.txt`: the one-paste install prompt from §Install, filled in with the version. `pack --mail --split 24` additionally cuts the mail zip into `evergreen-<version>-mail.zip.part01`, `.part02`, ... for routes with a small per-attachment ceiling (a mail connector that carries attachments as base64 through the model, for one); the prompt tells the recipient to join them in order.

The archive includes `profile/` (your preferences and environment facts), so a copy for someone else uses `python scripts/evergreen.py pack --share [--mail]` instead: `evergreen-<version>-share.zip` has no `profile/`, ships a config with no address and `notify.auto` off so their install mails nobody, and names their marketplace `my-local`. A share pack never baselines your install and never tags the trunk.

## One public trunk, many clones

The trunk is the public repository https://github.com/m4bwav/evergreen-protocol (`git.upstream` in `evergreen.config.json`, branch `master`); every install is a clone of it, keeps itself current with `pull`, and sends improvements to the protocol, skills, scripts or templates back as pull requests that `publish` opens on its own (protocol 1.5, `PROTOCOL.md` §10). Private facts (`profile/`, the address and paths in the config, hostnames) never travel to it: a clone holding real ones publishes through a scrubbed snapshot. When the plugin changes itself somewhere (a refresh, a learning, an environment fact, a test run), `evergreen.py publish` commits the plugin's tree with a subject that names the new entries and pushes: a clone the host lets write to `master` (a maintainer's) pushes there after a rebase; any other clone pushes `update/<env>-<stamp>` and opens a pull request with `gh` against the trunk. The role comes from the remote (a dry-run push), or is pinned per machine with `git.role` / `EVERGREEN_GIT_ROLE`; `publish --branch` sends any change through a pull request, which is the rule for scripts, hooks and the protocol even from a maintainer's clone. It runs after `checked`, `bump` and `tested` on the plugin and from Claude Code's `SessionEnd` hook (the owner's editing clone stays quiet there, `notify.report_trunk`). The append-only logs merge by union through `.gitattributes`, so two clones adding entries keep both; a rebase that still conflicts turns into a pull request rather than a forced push. `evergreen.py pull` fast-forwards a clone and says when the tool's cached copy needs a reinstall. Set-up and failure cases are in `skills/evergreen-publish`; which route suits which machine is in `protocol/PORTABILITY.md`.

Email is the fallback for a machine that cannot reach the repository (`update.transport: "email"`, or `EVERGREEN_UPDATE_TRANSPORT=email`): `notify` builds an update bundle and emails it to `notify.to` through classic Outlook, Microsoft Graph or Gmail SMTP, or leaves it in `EVERGREEN_HOME/outbox/` for an agent; at the trunk, `evergreen.py merge` folds the bundle, patch or saved email in (entry union with ID renumbering, `evergreen.json` as data, git 3-way for the rest; never `evergreen.config.json`, code only with `--allow-code`). Details in `skills/evergreen-notify` and `skills/evergreen-merge`.

The repository holds `evergreen.config.json` (store paths, the owner's address) and `profile/` (the owner's preferences and environment facts). Keep it private; give other people read access or a fork, or hand them a `pack --share` archive, which carries neither.

## License

MIT.
