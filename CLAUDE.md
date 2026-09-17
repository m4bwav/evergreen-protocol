@AGENTS.md

# Claude notes

- Skills in this plugin: evergreen-refresh, evergreen-learn, evergreen-map, evergreen-convert, evergreen-new, evergreen-audit. Subagents: evergreen-researcher, evergreen-mapper.
- Auto-memory: keep one-line pointers to evergreen learnings in MEMORY.md; the canonical text lives in the unit's LEARNINGS.md.
- The SessionStart hook prints due units; when it does, finish the user's task first, then run evergreen-refresh.
