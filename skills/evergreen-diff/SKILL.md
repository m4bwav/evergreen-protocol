---
name: evergreen-diff
description: "Show what the evergreen plugin changed about itself since it was installed or last reported: an update bundle with a human digest (new changelog, research and learning entries, state changes, file list) and a unified diff against the install baseline. Use on 'what changed in evergreen', 'generate the diff', 'diff the plugin', 'what did the plugin update', 'build the update bundle', 'anything to send home', or before evergreen-notify and evergreen-merge. Also to set or repair the baseline ('rebaseline', 'the diff shows the whole upgrade')."
---

# Evergreen diff

One bundle: `UPDATE.md` (digest), `changes.patch` (git-style unified diff, blob ids included so a git trunk can 3-way merge it), `manifest.json` (hashes, baseline, state). Protocol: `<plugin root>/protocol/PROTOCOL.md` §10.

Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path (`python` on Windows, `python3` on macOS and Linux (whichever answers `-c "import sys"`; the hook probes the same way)). The sync commands live in `scripts/evergreen_sync.py`, stdlib only.

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If `contradiction` is set or today is on or after `next_due`, say so in one line, finish this task, then run `evergreen-refresh` on the plugin root in the same session.

## Step 1: orient

`EG where` prints the plugin root, the store, this machine's environment name, the baseline (when it was taken and from which pack), whether the folder is a git repo, notify readiness, the last send, and any unsent bundles. Read it once; it answers most questions before any diff is made.

## Step 2: the baseline

The baseline is the snapshot the diff is measured from, kept in `EVERGREEN_HOME/baselines/evergreen/`. It is taken automatically when: a publish pushes, a pull fast-forwards, the trunk packs (the shipped state), an install still matches its `MANIFEST.json` on the first diff, an email send succeeds, or a bundle merge completes. Only these cases need a hand:

- "No baseline" and the files were already edited: `EG baseline --from <the pack zip this install came from>` (the archive is the true base). Copies of every pack the trunk built are in the trunk's `EVERGREEN_HOME/packs/`.
- The diff shows the whole upgrade after a reinstall: same fix, `--from` the new pack zip.
- Deliberately start over from the current tree: `EG baseline --note "why"`.

`EG baseline --show` prints what is there.

## Step 3: build and read the bundle

```
EG diff              # prints UPDATE.md and the bundle path
EG diff --stdout     # the raw patch only
EG diff --json       # {bundle, id, files, content_hash}
```

Bundles land in `EVERGREEN_HOME/outbox/<stamp>-<env>-<hash8>/` with a `STATUS` file (`unsent`, `sent via ...`, `pending-human`). An unsent bundle with identical content is reused rather than duplicated. "No changes since the baseline" is the normal answer on most days.

Read the digest before passing it on: new `C-`, `R-`, `L-` entries listed by ID; `evergreen.json` deltas (interval, dates, history, counts); every file with added and removed line counts. Changes outside the logs (protocol, skills, scripts, templates) deserve a sentence to the user, since those are what a merge can conflict on.

## Step 4: what next

- Publish it: `evergreen-publish` (`EG publish`: commit and push to `master` as maintainer, or an update branch and a pull request; the script already tries after every `checked` and at Claude Code session end). `git diff` and `git log origin/master..HEAD` in the clone show the same content in git's own terms.
- No route to the repository from this machine: `evergreen-notify` (email) with `EVERGREEN_UPDATE_TRANSPORT=email`, then `evergreen-merge` at the trunk with the bundle folder, its `changes.patch`, or the email saved as text.

No shell that reaches the plugin (Cowork sandbox)? Run `EG` on the host through Desktop Commander, or read the bundle files with whatever file tool reaches `EVERGREEN_HOME`.

## While working: capture learnings

A baseline that was wrong, a file the diff should ignore, a noisy state delta: record it in the plugin's LEARNINGS.md with Trigger and Hypothesis.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
