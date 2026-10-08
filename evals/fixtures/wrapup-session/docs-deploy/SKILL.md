---
name: docs-deploy
description: "Publish the docs site. Use when the user asks to deploy or publish the docs."
---

# Docs deploy

Fixture skill for the evergreen eval suite (case action-5). The session that used it is `../session.jsonl`.

## Step 1

Run `python deploy.py --check`, then `python deploy.py --publish`.

## Maintenance

Learnings: [LEARNINGS.md](LEARNINGS.md). State: `evergreen.json`.
