---
max_turns: 8
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
runs: 3
---

Under the evergreen wrap-up, a session's harvest has five candidates. For each, answer KEEP (with where it goes) or DROP, one line each, labelled (a) to (e):
(a) The feature is finished; 14 files changed.
(b) `az monitor app-insights query` failed with 403 twice; `az login --tenant <id>` fixed it, and the next query returned rows.
(c) `python scripts/build.py --all` ran 9 times this session, about 4 minutes each; `--changed` would rebuild only the touched pages.
(d) The user said: never push straight to master in this repo, always open a pull request.
(e) The CLI's flags are listed in the README.
