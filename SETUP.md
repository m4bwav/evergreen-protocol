# Setup: evergreen

What the plugin ([README.md](README.md)) needs outside itself, what each piece is for, and how to get it on each environment met so far. Format and rules: [protocol/SETUP.md](protocol/SETUP.md). Check with `python <plugin root>/scripts/evergreen.py setup <plugin root>`. The markdown works with no script at all; only the conveniences below need these tools.

## Needs

| id | kind | check | for | if missing |
|---|---|---|---|---|
| python | command | `python \| python3 >= 3.9` | every script: audit, state and interval math, links, lint, worth, setup, publish and pull | optional: follow the protocol by hand (INTERVALS.md hand rule, edit evergreen.json directly) |
| git | command | `git --version` | staying current (`pull`) and sending improvements back (`publish`) | optional: install from a release archive; updates arrive by hand or by the email route |
| gh | command | `gh --version` | opening the pull request when `publish` pushes a branch | optional: the branch is pushed and the pull request is opened by hand on GitHub |
| claude | command | `claude --version` | `claude plugin eval` suites and the `worth --ab` and `--heavy` runs (TESTING.md §6, §8) | optional: run cases through the `evergreen-tester` agent or the harness this environment has |

## Install

The shared book ([setup/RECIPES.md](setup/RECIPES.md)) has recipes for all four; nothing here differs from it.

## Environments met

| date | os | harness | missing | notes |
|---|---|---|---|---|
| 2026-10-02 | windows | claude-code | none | first check; all four present |
