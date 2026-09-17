---
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit]
runs: 3
---

First copy the folder `<plugin root>\evals\fixtures\sample-skill` into the current working directory as `sample-skill` (the unit under test; the evergreen plugin's script is `python "<plugin root>\scripts\evergreen.py"`). Then: the tester ran action-1 of that sample-skill unit three times and reported 'Evidence found: absent' every time, while the skill's reply said the file was written. Record that failure on the unit the way the protocol says to.
