# Setup: evergreen

What the plugin ([README.md](README.md)) needs outside itself, what each piece is for, and how to get it on each environment met so far. Format and rules: [protocol/SETUP.md](protocol/SETUP.md). Check with `python <plugin root>/scripts/evergreen.py setup <plugin root>`. The markdown works with no script at all; only the conveniences below need these tools.

## Needs

| id | kind | check | for | if missing |
|---|---|---|---|---|
| python | command | `python \| python3 >= 3.9` | every script: audit, state and interval math, links, lint, worth, setup, publish and pull | optional: follow the protocol by hand (INTERVALS.md hand rule, edit evergreen.json directly) |
| git | command | `git --version` | staying current (`pull`) and sending improvements back (`publish`) | optional: install from a release archive; updates arrive by hand or by the email route |
| gh | command | `gh --version` | opening the pull request when `publish` pushes a branch | optional: the branch is pushed and the pull request is opened by hand on GitHub |
| claude | command | `claude --version` | `claude plugin eval` suites and the `worth --ab` and `--heavy` runs (TESTING.md §6, §8) | optional: run cases through the `evergreen-tester` agent or the harness this environment has |
| everlast-protocol | manual | claude plugin list shows everlast-protocol | evergreen-wrapup hands project solutions, decisions, plans and the handoff to `everlast-capture` and searches project docs with `everlast.py search` | optional, offer it, never push it: without it the wrap-up writes project notes to the repository's `ai-docs/` log and searches with grep |

## Install

The shared book ([setup/RECIPES.md](setup/RECIPES.md)) has recipes for python, git, gh and claude; nothing here differs from it.

### everlast-protocol

Install only when the user asks for it; mention it once when a wrap-up falls back to the `ai-docs/` log.

- claude-code: `git clone https://github.com/m4bwav/everlast <plugins root>/everlast-protocol`, then `claude plugin marketplace add <plugins root>/everlast-protocol` and `claude plugin install everlast-protocol@everlast --scope user`; its own README covers the private vault it asks for (manual)
- any: paste `templates/INSTALL-PROMPT.txt` from https://github.com/m4bwav/everlast into the agent (manual)

## Environments met

| date | os | harness | missing | notes |
|---|---|---|---|---|
| 2026-10-02 | windows | claude-code | none | first check; all four present |
