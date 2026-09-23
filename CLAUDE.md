@AGENTS.md

# Claude notes

- Skills in this plugin: the thirteen under `skills/` (evergreen-refresh, -learn, -map, -convert, -new, -audit, -test, -tune, -publish, -merge, -pack, -diff, -notify). Subagents: evergreen-researcher, evergreen-mapper, evergreen-tester.
- Auto-memory: keep one-line pointers to evergreen learnings in MEMORY.md; the canonical text lives in the unit's LEARNINGS.md.
- The SessionStart hook prints due units, verify-at-use claims that are due and learnings due for consolidation; when it does, finish the user's task first, then run evergreen-refresh (or re-check the claims, or consolidate with evergreen-learn).
