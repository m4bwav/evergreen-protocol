---
type: llm
name: treats it as the user's own work
criteria: The reply treats the request as ordinary work on the user's own code or repository (tests, a bug fix, a feature branch) and does not invoke or recommend any evergreen plugin skill for it. Saying that an evergreen skill does not apply, or passing on a notice the plugin printed at session start (such as its one-time question about contributing), is fine; proposing to refresh, tune, test or publish an evergreen unit as the way to handle this request is not.
weight: 1
---


