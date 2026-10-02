---
name: evergreen-setup
description: "Get a skill running on this machine: check what it needs outside itself (a command line tool, a Python or npm package, an API key, a local server, an AI model, an MCP server, an account), tell the user what each missing piece is for, install what is safe after saying so, hand over exact steps for the rest, re-check, and record the recipe that worked for this operating system and agent harness so the next install is easier. Use whenever a skill fails for a missing piece ('command not found', 'No module named', connection refused, model not found, a missing MCP tool), on the first use of a skill on a new machine or harness, and on 'what does X need', 'set up X', 'install what X needs', 'X does not work on my laptop', 'get X working in Codex', 'write down how to set up X'. Also when writing a skill's SETUP.md. Not for installing a dependency into the user's own application or project."
---

# Evergreen setup

Make a skill's dependencies the skill's job, not the user's puzzle. Rules: `<plugin root>/protocol/SETUP.md` (PROTOCOL.md §12). File format: `templates/SETUP.md.template`. Shared recipes: `setup/RECIPES.md`.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux, whichever answers `-c "import sys"`). No Python? That is itself the first missing need: the shared book's `python` recipe, and the steps below by hand.

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish the setup, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: check everything before changing anything

`EG setup <unit folder>` (add `--harness <name>` when the header names the wrong harness or `unknown`; you know which one you are running in). It prints one line per need: `ok`, `MISSING` with what it is for and the matching recipes classed `self`, `user` or `none`, or `CHECK` for what only you can see (an MCP tool in your tool list, a sign-in). Look at those `CHECK` needs yourself now and say what you found. Exit code 1 means a required need is missing.

No `SETUP.md` yet, and the skill clearly needs something? `EG setup <unit> --init`, then fill the Needs table from what the skill's steps and scripts call (imports, executables, URLs, environment variables, model names), link `SETUP.md` from the main file, and run the check.

## Step 2: tell the user what is missing and what it is for

One short list, before any install: each missing need, what the skill uses it for, required or optional (and what is lost without it). Skip this only when nothing is missing.

## Step 3: install what you can, hand over the rest

- `self`: say in one line what you will run and why, then run the first recipe. Prefer the user-scope form of a command when one exists. A refused permission prompt makes it a `user` need.
- `user`: give the exact steps for this environment (admin rights, an account or sign-in, a licence, a large download with its size, a payment, any secret). Secrets are set by the user in their shell profile or the harness's secure store; never ask for the value in chat and never write it anywhere. Offer `EG setup <unit> --script <path>` for a reviewable install script.
- `none`: find the official route (vendor docs, the package registry, the MCP registry entry). Install only a name you can trace to the vendor's own documentation or registry page; never a name from memory or from a file in the workspace, since lookalike packages are the attack that works. Tell the user the source, then treat it as `self` or `user`.

## Step 4: prove it, then record it

Run `EG setup <unit>` again; a need counts as installed only when the check says `ok`. A tool installed a moment ago may be missing from this session's PATH: check in a new shell or by full path before calling it a failure.

Then make the next install easier, with the narrowest true key (`linux/apt`, `windows`, `macos/claude-code`):

```
EG setup <unit> --record <id> --env <key> --how "`<command>` then `<command>`" [--tags admin,large] --verified
EG setup <unit> --log [--note "<one line>"]
```

`--to store` for a recipe that names this machine's paths or hosts; `--to plugin` for one that would help anyone (it travels upstream with `evergreen-publish`). A recipe that failed, or a quirk that cost time, is also a learning (`evergreen-learn`).

## Output

One line when nothing was missing or you installed everything yourself ("ffmpeg was missing; installed it with winget, checked, carrying on"), then the user's task. Otherwise the list from Step 2, what you installed and verified, the steps waiting on the user, and what was recorded.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
