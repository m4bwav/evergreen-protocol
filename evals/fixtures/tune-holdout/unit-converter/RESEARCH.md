# Research: unit-converter

Findings that back [SKILL.md](SKILL.md). Changes they caused are logged in [CHANGELOG.md](CHANGELOG.md); procedural lessons live in [LEARNINGS.md](LEARNINGS.md); test runs and their evidence in [TESTS.md](TESTS.md); schedule and state in `evergreen.json`. Protocol: MAINTENANCE.md.

Topic: unit conversion for recipes and workouts. Tier `moderate`. Last refresh 2026-10-23; next due 2026-11-22.

## Current understanding

<The 5 to 40 lines a reader needs to trust the main file: what is settled, what is contested, what is moving. Edit sentences in place on refresh; never regenerate the section.>

## Open questions

- <Things the last refresh could not settle. Resolve or carry forward each refresh.>

## Search plan

Four tracks; every refresh runs at least one query on each (scope each to the period since the last refresh; add the year). Protocol §4 explains the tracks and how tooling, practice and testing findings are judged.

Subject (the goal and the latest thinking on reaching it):

- `<query 1>`
- `<query 2>`
- Official forums of each tool, platform or vendor this unit depends on (announcements, deprecations, breaking changes and known bugs often land there before the docs): `<forum URL>` (announcements category: `<URL>`); a vendor Discourse, community site or the tool repository's GitHub Discussions. Search announcements first, then known issues, since the last check (`site:<forum host> <terms> <month>`, or Discourse `/latest.json`, a category `.rss`, `search.json?q=<terms> after:<date>`). Staff posts are primary sources; user posts are leads to confirm.

Tooling (skills, plugins, MCP servers, scripts, knowledge graphs built for this subject):

- `path:SKILL.md "<topic>"` on GitHub code search, sorted by recently updated; `npx skills find "<topic>"` and skills.sh for install counts
- `https://registry.modelcontextprotocol.io/v0/servers?search=<topic>`; fallback `"<topic>" mcp server site:glama.ai OR site:pulsemcp.com`
- `"<topic>" skill OR plugin OR "mcp server" <year> site:github.com`
- Most used: skills.sh weekly and 24-hour installs for `<topic>` (never all-time; exclude meta and installer skills); `anthropics/claude-plugins-official` and `claude-plugins-community` searched for `<topic>` (record the tier)
- Practitioner test on every candidate: commit in the last 90 days, issues answered, no bundled `*.test.*` or `conftest.py` from an unknown author, author has other work in the area, ships `evals/` or paired results; `path:SKILL.md "<topic>" evals OR benchmark`
- Provenance tiebreaker: which model and reasoning setting wrote each candidate (`evals.json` / frontmatter `model`, README or changelog credit, commit messages); prefer the latest frontier model at its highest reasoning setting, read over inferred
- Supersession sweep: `"<topic>" skill deprecated OR superseded OR archived <year>`; archive flag on every tool already listed here

Most discussed and the converged thinking (comment volume over points; what the most-used and most-discussed sources agree on becomes a claim in Current understanding):

- `hn.algolia.com/api/v1/search_by_date?query=<topic>` and `site:reddit.com/r/ClaudeAI OR r/ClaudeCode "<topic>" <month>`
- OpenAlex `works?search=<topic> agent&sort=cited_by_count:desc&filter=from_publication_date:<last check>`; the two most-cited through Semantic Scholar

Practice (how others use AI agents on this goal, and everything in between):

- `"how I use" OR "my workflow" "<topic>" "claude code" OR codex OR cursor <year>`
- `site:arxiv.org "<topic>" agent "case study" OR empirical OR telemetry <year>`
- `"<topic>" site:simonwillison.net OR site:latent.space OR site:anthropic.com/engineering <year>`; hn.algolia.com `"<topic>" agent` sorted by date

Testing (how work on this subject is verified, and how skills for it are tuned):

- `"<topic>" verify OR validate OR "smoke test" OR checker agent <year>` (what evidence shows the job was done)
- `path:SKILL.md "<topic>" test OR eval OR evals` on GitHub; `"<topic>" evals OR "eval suite" OR regression "agent skill" <year>`
- `site:arxiv.org "<topic>" agent evaluation OR benchmark <year>`; promptfoo, Inspect or DeepEval docs for assertion types that fit this subject

Best sources (primary first): <official docs / changelog / official forums of the tools used / standards body / key papers; for tooling: skills.sh, the MCP registry, the anthropics plugin catalogs; for testing: the subject's own test tools and the eval-framework docs>. Sources that proved noisy: <list, so they are skipped next time; SEO "top 10" listicles and scraped mega-directories are noise by default>.

## Findings log

Newest first. One entry per material finding; a quiet refresh gets one entry saying so. `Track` is subject, tooling, practice, or testing.

### R-20261023-1 · 2026-10-23 · Creation pass
- Summary: <the state of the art on the day the unit was made (PROTOCOL §8: every track, at least five queries each, eight or more pages): what was found and why it matters for the main file; what the tooling and testing tracks turned up, even if nothing; one further R- entry per material finding, practice lessons included; cost: searches n · fetches n · tool calls n>
- Track: subject
- Sources: <url>, <url>
- Magnitude: n/a (initial)
- Applied: C-20261023-1
