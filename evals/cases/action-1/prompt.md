---
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit]
runs: 3
---

Copy the folder `<plugin root>\evals\fixtures\sample-skill` into the current working directory as `sample-skill-copy`, then make that copy evergreen with a test suite. The evergreen plugin's script is `python "<plugin root>\scripts\evergreen.py"`.
