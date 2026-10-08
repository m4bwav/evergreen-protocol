---
type: llm
name: 'expectations'
---

PASS if the reply meets every one of these:
- (a) and (e) are dropped: completion news and something derivable from the README
- (b) is kept as a setup or access recipe or a project solution with the verified command
- (c) is kept as a script or process improvement (use or add the faster flag), with the saving named
- (d) is kept as a rule in the narrowest home: a hook or branch protection, or the repository's AGENTS.md or the user profile
- regex on the answer: (?is)\(a\)[^
]*drop
- regex on the answer: (?is)\(e\)[^
]*drop
FAIL if any is missing or contradicted.
