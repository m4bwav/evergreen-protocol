# AGENTS.md

This repo is the evergreen plugin: self-maintaining, self-proving skills and knowledge for AI agents. Read `README.md` for the shape and `protocol/PROTOCOL.md` for the rules. Structure: `protocol/` (spec), `skills/*/SKILL.md` (thirteen skills), `agents/` (three subagents), `scripts/evergreen.py` (stdlib CLI; run `python scripts/test_evergreen.py` before changing the interval rule), `templates/`, `profile/`, `hooks/`, `evals/` and `TESTS.md` (the plugin's own suite and run log).

## Commands

- Self-test: `python scripts/test_evergreen.py`
- Audit with checks: `python scripts/evergreen.py audit --checks`
- Validate plugin structure (Claude Code): `claude plugin validate .claude-plugin/plugin.json`

## Style

- Plain markdown, relative links, no tool-specific syntax in shared files. Imperative voice in skill bodies. No em dashes. Keep SKILL.md bodies under 200 lines and put detail in `protocol/` or `references/`.
- Delta edits only. Never regenerate a RESEARCH, CHANGELOG, or LEARNINGS file.
- Every change to this repo gets a `C-` entry in `CHANGELOG.md` with `because:`.
- This repo is the trunk (protocol 1.6, `PROTOCOL.md` §10). Log entries, state and claim edits may go straight to `master` from a maintainer's clone (`python scripts/evergreen.py publish`); scripts, hooks and protocol changes go through a pull request (`publish --branch`). Never force-push; never rewrite `master`.

## Boundaries

- Always: run the self-test after touching `scripts/evergreen.py`; keep `templates/` and the standalone `MAINTENANCE.md.template` in sync with `protocol/` when the rules change.
- Ask first: changing tier bounds or the interval rule (they are cited by every converted unit); adding a hook event; changing entry ID grammar.
- Never: put secrets, addresses, or health details in `profile/`; write state into an installed copy instead of the `source` path.

## Evergreen (self-maintaining knowledge)

- Preferences: read `profile/AI-PREFERENCES.md` before substantial work. Environment facts: `profile/ENVIRONMENTS.md`.
- Model knowledge is a stale snapshot on anything fast-moving. Search primary sources before asserting time-sensitive facts.
- Research the subject and the AI ecosystem around it (PROTOCOL §4, the four tracks): the goal itself, the skills, plugins, MCP servers, scripts and knowledge graphs built for it, how others use agents on the same goal, and how they test that the job was done.
- Before using any folder that contains `evergreen.json`, read it. If `next_due` has passed or `contradiction` is set, say so in one line, do the task, then refresh in the same session (`protocol/PROTOCOL.md` §4). If `tests.failing` is non-empty, say so and run `evergreen-tune` after the task.
- A skill is proven by evidence outside the transcript (a tool call in the trace, a file, a marker, a record), never by its reply. Run a skill's suite after editing it (`evergreen-test`); when a skill fails in use, reproduce, classify, learn, research if stale, fix, re-run (`evergreen-tune`, `protocol/TESTING.md`).
- When corrected, when the same error happens twice, when a workaround is found, or when an environment fact is discovered, write a learning immediately (`LEARNINGS.md` of the unit in use; else the codemap's Gotchas; else `profile/`). Check existing entries first; include Trigger and Hypothesis.
- Codemaps live in `$EVERGREEN_HOME/maps/<slug>/`. They may be stale, incomplete, or confused: verify load-bearing claims in code and check drift against the stamped sha.
- New skills are evergreen by default unless asked for a plain skill.
- Before finishing a substantial task, ask: did I learn something a future session would need? If yes, record it.
