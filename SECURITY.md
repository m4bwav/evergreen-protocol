# Security policy

## Reporting a problem

Open an issue or a pull request and I'll take a look. A pull request with the fix is the quickest route.

You can also report privately: open the repository's **Security** tab and choose **Report a vulnerability**.

This is a one-person project with no bug bounty and no response deadline. I'll reply when I can and say what I plan to do. Good-faith testing on your own copy is welcome.

## Supported versions

Only the latest release on the default branch gets fixes.

## Scope

The skills' instructions and scripts run on your machine with your agent's permissions. In scope: anything that leads the agent to run commands, write files, fetch URLs or share data beyond what the skill says it does. That includes instructions planted in a page or file the skill reads (prompt injection). Out of scope: bugs in the agent tool itself (Claude Code, Copilot, Codex, Cursor); report those to their makers.
