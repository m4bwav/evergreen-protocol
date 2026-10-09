---
name: evergreen-wrapup
description: "End-of-session wrap-up that turns what a work session learned into lasting improvements, keeping only what will save time or tokens or raise quality: harvest the transcript (corrections, refused calls, errors, repeated commands, token sinks, slow calls, files and stores touched), drop what fails a usefulness gate, then send each survivor to its narrowest home (a test, hook or script; a skill's LEARNINGS or a fix to the skill; project docs and handoff; a knowledge base, including vaults and notes folders no skill owns; the user profile; an install recipe) and improve the scripts and processes that cost the most. Use when the user says 'wrap up', 'wrap-up', 'wrapup', 'end of session', 'consolidate what we learned', 'retro', 'compound this', 'what should we keep from this session', 'before I close this', or at the end of a long session that changed skills, scripts or several repos. Not for capturing one lesson mid-task (evergreen-learn), a handoff or project note alone (everlast-capture), or merging a unit's LEARNINGS entries (evergreen-learn consolidation)."
---

# Evergreen wrap-up

A session's lessons die with its context unless something writes them down, and most of what could be written down is noise that costs tokens in every later session: generated context files and self-written skills measure neutral to harmful unless they are specific and verified (RESEARCH.md R-20261008-2, R-20261008-3). The wrap-up does both halves of the job: it finds every candidate in the transcript, not just what the model happens to remember, and it keeps only what passes the gate. Routing: `protocol/PROTOCOL.md` §5. Entry format: `protocol/LEARNINGS-FORMAT.md`.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux).

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish the wrap-up, then run `evergreen-refresh` on the plugin root.

## Step 1: harvest (two sources)

1. The transcript: `EG wrapup` (the current session; `--session <id>` for another, `--json` for the raw data). It prints IDs: C corrections, D refused calls, E errors, R repeated command shapes, T token sinks, S slow calls, plus skills used, files changed per repository with the stores there (`ai-docs/`, `AGENTS.md`, evergreen units), K notes and vaults outside any repository that the session edited or read, web research and compactions. No transcript (another harness, a cloud sandbox, a desktop or web chat, whose transcript is not on disk): skip to 2 and say so. In a chat or sandbox that has a local connector (Desktop Commander, a filesystem MCP), the rest still works on the host: run `EG` through the connector's process tool by its host path, and read and write stores through its file tools.
2. Your own account of the session, for what a transcript cannot show: decisions and their reasons, options rejected, a belief about the code that turned out false, what the user seemed to want but did not say, work left unfinished. Write these as candidates too, `M1`, `M2`...
3. The session-start lines: units flagged `consolidate:N>M`, `failing-tests` or stale that this session touched join the list.

One list, every candidate one line. Expect most of it to be noise.

## Step 2: gate (keep only what pays)

A candidate survives only if all four hold. Ask them in order and stop at the first no.

| Test | Question | Fails when |
|---|---|---|
| Material | If this were never written, would a future session repeat the error, redo the work, or deliver worse output? Name the cost: minutes, tokens, a wrong result. | completion news, effort spent, diff size, a one-off with no reuse |
| Non-derivable | Could a fresh session get it from one file read, one grep, `--help`, or the code itself? | it restates the code, a README, or the model's general knowledge |
| Recurring | Did it happen twice, or will the task it belongs to come back? A dead end that cost 15 minutes or more counts the first time. | a single event in a task that will not recur |
| Verified | Is there evidence from this session: command output, a passing test, the user's own words? | a guess; record it as an open question in a plan instead, or drop it |

Then search before writing (`EG search "<lesson>" --kinds learnings -n 5`; `everlast.py search` for project docs; the native memory index). Already recorded: update that entry (a new occurrence, a sharper rule, `helpful` +1) rather than adding a near-duplicate. Contradicted: retire or supersede the old entry.

Weigh what a line costs where it lands: a line in an always-loaded file (CLAUDE.md, AGENTS.md, MEMORY.md, a skill's description) is paid in every session, so it must name the failure it prevents and fit the file's budget; a file read on demand is nearly free until it is opened.

## Step 3: route each survivor (narrowest home wins)

| Survivor | Home | Done by |
|---|---|---|
| A rule a check can enforce | a test, lint rule, hook or assertion, plus one `AGENTS.md` line naming it | edit and run it now |
| A manual step repeated three times, or slow or costly work (R, S, T) | a script, alias or flag: extend an existing script first; a new one only when nothing fits | Step 4 |
| A skill misbehaved (did not fire, wrong route, said it acted and did not) | that skill's `LEARNINGS.md`, then the fix | `evergreen-learn`, then `evergreen-tune` |
| A skill's claim proved wrong | the claim, fixed in place, a `C-` entry, `EG flag <unit> --contradiction` | `evergreen-learn` Step 3 |
| A skill or plugin's knowledge base got a fact or method worth keeping | its `RESEARCH.md`, `references/` or knowledge base (a plugin's `kb/`, a scout beat's notes) | that unit's own curate skill when it has one |
| A fact, finding, reference or decision that belongs in a knowledge base no skill owns (a vault, a folder of reports or notes) | that knowledge base, when the session makes it clear which: a K row, a folder the work used, the user's words. Follow its own conventions (its index or README: one note per topic, an index line, relative links, a dated source); update an existing note before adding one | edit it directly. Unclear where: do not search the disk for a home; name the item in the report, or ask the user when it matters |
| A project solution, decision, plan, or unfinished work | the project's doc set and `HANDOFF.md` | `everlast-capture` (else the repo's `ai-docs/` log) |
| A user correction, preference or refusal (C, D) | the user profile (`user/PROFILE.md` in an everlast vault, else `profile/AI-PREFERENCES.md`) and a pointer in native memory | `everlast-capture` or `evergreen-learn` |
| A fact about a machine or tool | `ENVIRONMENTS.md` (vault user tier, else `profile/`) | same |
| How to install or get access to something | the skill's `SETUP.md` recipe | `EG setup <unit> --record ... --verified` |
| A procedure used on three or more dates | a new skill, at most one per wrap-up, as a trial | `everlast.py promote-scan`, then `evergreen-new` and `evergreen-test` |
| A lesson general to a shared plugin or public repository | that repository, by its own contribution rules (pull request) | the repository's `AGENTS.md` |

Nothing from a personal knowledge base goes into a shared repository. Content naming people, credentials, internal hosts or customers goes only to a private tier (everlast `--private`, or the user tier), never into a shared repository.

When the same kind of knowledge lands in the same place across wrap-ups, say so in the report: a usage pattern is the point to write that destination into a skill, not before.

## Step 4: improve scripts and processes (the time and token savers)

For each R, S, T or E candidate that survived:

- Estimate the saving: how often it recurs times what it costs each time (minutes, tokens from the T line, seconds from the S line). Skip what saves less than the change costs to make and maintain.
- Small and testable now (a flag, a filter on a noisy output, a wrapper for a repeated command chain, a retry or a clear error message in a script that failed): make it, run it before and after, and record the measured difference in the commit or `C-` entry.
- Larger: a plan entry (`everlast-capture`, kind `plan`) with the evidence, the estimated saving and the next single action, so the next session can pick it up cold.
- A wasteful habit rather than a missing tool (polling instead of a background run, re-reading a whole file, a broad search where one grep would do): a rule in the narrowest home, phrased as the faster route, with the measured cost that justifies it.

## Step 5: write, deltas only

Write each item through its owner in Step 3, in that owner's format, as a small delta: add, update or retire one entry; never regenerate a file. Every entry carries its evidence (the command and the output that proved it, the error string, the harvest ID) and, for anything tied to an outside tool version or an open bug, what retires it. Edits to always-loaded files during an unattended run (headless, a hook, a schedule) are proposed in the report, not applied.

## Step 6: verify

Run the checks for what changed: the repository's tests after a script edit, `EG worth <skill> --lite` and the skill's suite (`evergreen-test`) after a `SKILL.md` edit, `everlast.py lint <repo> --all` after project docs, `EG links <unit>` after moving files. Fix what fails before reporting.

## Step 7: report

A short table: each kept item, where it went (path or pull request), and the saving or failure it prevents. Then one line with the count dropped at the gate, anything proposed and not applied, and what still needs the user (a review, a merge, a decision). Commit and push or open pull requests by each repository's rules. "Nothing worth keeping" with the reason is a valid result.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](https://github.com/m4bwav/evergreen-protocol/blob/master/RESEARCH.md), [CHANGELOG.md](https://github.com/m4bwav/evergreen-protocol/blob/master/CHANGELOG.md), [LEARNINGS.md](https://github.com/m4bwav/evergreen-protocol/blob/master/LEARNINGS.md), [TESTS.md](https://github.com/m4bwav/evergreen-protocol/blob/master/TESTS.md).
