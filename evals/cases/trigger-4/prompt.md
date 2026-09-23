---
max_turns: 8
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
runs: 3
---

No, the build box's Python is /opt/py311/bin/python3, not the system python. I've told you that before. Make sure that sticks for next time.

(For this run: start the job, and stop after the first two or three tool calls with a one-line note of which skill you invoked and what you would do next.)