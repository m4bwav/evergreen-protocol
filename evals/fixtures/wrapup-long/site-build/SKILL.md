---
name: site-build
description: "Build the docs site and check its links. Use when the user asks to build, rebuild or link-check the docs site."
---

# Site build

Fixture skill for the evergreen eval suite (case action-6). The session that used it is `../session.jsonl`.

## Step 1

Run `python build.py --all` from this folder and report the link check.

## Maintenance

Learnings: [LEARNINGS.md](LEARNINGS.md). State: `evergreen.json`.
