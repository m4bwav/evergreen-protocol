---
type: regex
name: action-1 in tests.failing
target: {source: file, path: sample-skill/evergreen.json}
pattern: \"failing\"\s*:\s*\[\s*\"action-1\"
match: contains
arm: both
---


