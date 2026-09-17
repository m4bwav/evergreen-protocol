# Portability

Part of the [Evergreen Protocol](PROTOCOL.md). Evergreen has to work wherever an agent runs: Claude Code, Cowork, Copilot, Codex, Cursor, Gemini CLI, and whatever comes next. So the protocol is plain markdown plus one JSON state file plus optional Python scripts. Nothing requires hooks, a specific model, or a specific tool. Evidence: [../RESEARCH.md](../RESEARCH.md) R-20260901-6.

## The lowest common denominator

- Plain markdown files, relative links, no tool-specific syntax in shared files (no `@imports`, no `${VARS}` outside Claude-only files).
- `evergreen.json` is small enough for an agent to read and edit by hand. The scripts are conveniences.
- `AGENTS.md` at a repo root is the cross-tool instruction surface (Linux Foundation standard; read by Codex, Cursor Agent mode, Copilot, OpenCode, Amp, Windsurf, and Gemini CLI with one config line). `CLAUDE.md` contains `@AGENTS.md` plus Claude-only notes.
- Skills live in `.agents/skills/<name>/SKILL.md` (the emerging cross-client convention from agentskills.io) and are mirrored or linked into `.claude/skills/` until every client reads the shared path.
- Hooks are the least portable feature (five schemas, several tools with none). Logic goes in `scripts/`; a hook is a one-line call. Tools without hooks rely on Step 0 in each unit.

## EVERGREEN_HOME

The plugin's own writable store: registry, codemaps, and units that do not live in a repo.

Resolution order: `EVERGREEN_HOME` environment variable → `evergreen.config.json` at the plugin root (`{"home": "..."}`) → `~/.evergreen`. Layout:

```
EVERGREEN_HOME/
  registry.json        all known units: name, path, kind, tier, source; plugin_root for pointer-mode units
  maps/<slug>/         codemaps (CODEMAP-FORMAT.md)
  units/<name>/        evergreen units that have no other home
  baselines/<key>/     snapshot each plugin copy diffs against (PROTOCOL.md §10)
  outbox/<bundle>/     update bundles (email route): UPDATE.md, changes.patch, manifest.json, files/, STATUS
  packs/               a copy of every archive the trunk built (the base a bundle merge may need)
  publish.json         git route: every publish (date, env, sha, push or branch, PR)
  notify.json, notify.log, merges.json   email send log, detached-run log (both routes), bundle merge log
```

A configured store on a drive the machine does not have (the shipped config names the trunk's) falls back to `~/.evergreen` with one note.

Sandboxed agents (Cowork's Linux sandbox, cloud runners) may not see the host path. Then either run the script on the host through a host-side tool (Desktop Commander `start_process` in Cowork), or follow the protocol by hand with whatever file tool reaches the path. The environment profile records which applies where.

## Four linking modes

A unit needs to find the protocol. Pick the mode when creating or converting, record it as `protocol` in `evergreen.json`.

1. Plugin-in-repo. The unit lives inside the evergreen plugin or in a repo that vendors it. Link relatively: `../../protocol/PROTOCOL.md` from `skills/<name>/SKILL.md`. Claude-only files may also use `${CLAUDE_PLUGIN_ROOT}/protocol/PROTOCOL.md`.
2. Pointer (default for units outside the plugin on a machine that has it). `protocol: "plugin"`. The script resolves it to the running plugin's `protocol/PROTOCOL.md`, or to `plugin_root` in the store's `registry.json` (written whenever the plugin registers itself); agents without the script read the short `MAINTENANCE.md` written from `templates/MAINTENANCE-POINTER.md.template`, which says how to find the plugin and carries only the few stable rules (Step 0, the hand rule) for when it is absent. A protocol change is then one plugin update, not an edit per unit. `evergreen.py init --pointer`.
3. Standalone unit. A skill that travels to machines with no plugin. `MAINTENANCE.md` is a condensed, self-contained copy of the protocol (Step 0, refresh, hand rule, learnings format, link rules). `protocol: "MAINTENANCE.md"`. It goes stale when the protocol changes; prefer the pointer mode whenever the plugin will be present.
4. Repo-level. A repo adopts the paradigm for its docs and codemap without any skill. `AGENTS.md` gets the evergreen section (templates/AGENTS.md.snippet); the unit files sit in `docs/` with `MAINTENANCE.md` (pointer or standalone).

## Installed copies are read-only

Several tools copy a plugin or skill into their own store on install (Cowork plugins under the app's data folder, Cowork `save_skill` skills, Claude Code marketplace installs). Edits to those copies are lost on reinstall and never reach the source. `evergreen.json.source` holds the canonical writable path. When Step 0 finds itself in an installed copy, it edits the source and the audit reports "reinstall needed" for units whose main file changed. Local-path installs (`claude plugin install <dir>` from a folder, or `--plugin-dir`) read the source directly and need nothing.

## Per-environment notes

| Environment | Instruction file | Skills | Hooks | Persistent memory | Notes |
|---|---|---|---|---|---|
| Claude Code | `CLAUDE.md` (+ `@AGENTS.md`), `.claude/rules/` | `.claude/skills/`, plugins | yes (SessionStart, SessionEnd with reason matcher, Stop, PreToolUse, PostToolUse with a tool-name matcher; SessionEnd hooks share a 1.5 s budget unless a per-hook `timeout` raises it, up to 60 s; the publisher detaches regardless) | auto-memory `MEMORY.md` (first ~200 lines loaded) | full evergreen: hook prints stale units at session start; SessionEnd publishes self-updates to the trunk repository (git push or PR; email fallback); PostToolUse on `Skill` writes the use log (TESTING.md §6); test harness: skill-creator's runner, else the tester agent; `claude plugin eval` only where that undocumented command runs |
| Cowork (Claude desktop) | space memory | plugins, `save_skill` | none (confirmed: Cowork ignores user, managed and plugin hooks; claude-code issue #40495 open, #63360 closed as its duplicate) | space memory files | Step 0 is the mechanism; host paths via Desktop Commander; installed plugin is a copy; no use log, so action cases need file or marker evidence; tests run through the tester agent |
| GitHub Copilot (CLI, VS Code, coding agent) | `AGENTS.md`, `.github/copilot-instructions.md`, `*.instructions.md` | yes (agent skills) | CLI: yes (`~/.copilot/hooks/*.json` or `.github/hooks/`, version 1: sessionStart, sessionEnd, agentStop, userPromptSubmitted, pre/postToolUse; camelCase payloads, `transcriptPath` only on agentStop) | none (files only) | reads CLAUDE.md and GEMINI.md too |
| OpenAI Codex | `AGENTS.md` (global + repo, ~32 KiB cap) | yes | yes (`~/.codex/hooks.json`, docs at learn.chatgpt.com/docs/hooks; SessionEnd synchronous, 1 s default, 3 s max; PostToolUse carries `transcript_path`) | `~/.codex/memories/` | `AGENTS.override.md` for personal, gitignored notes |
| Cursor | `.cursor/rules/*.mdc` + `AGENTS.md` (Agent mode) | yes | yes | project memories | Chat mode ignores AGENTS.md |
| Gemini CLI | `GEMINI.md`; set `.gemini/settings.json` `{"context":{"fileName":"AGENTS.md"}}` | yes | yes | `/memory add` appends to global GEMINI.md | |
| Windsurf | `.windsurf/rules/`, auto-discovers `AGENTS.md` | not listed | not documented | Cascade memories, not in repo | |
| Aider | none native; `.aider.conf.yml` `read: AGENTS.md` | no | no | none; auto repo map | |
| OpenCode / Amp | `AGENTS.md` | yes | plugin events / n/a | none / thread-scoped | |

Re-verify this table on refresh; it is the fastest-moving part of the protocol (tier `fast`).

## Self-updates: which route where

PROTOCOL.md §10. The default route is git: `evergreen.py publish` commits the clone and pushes to the trunk branch (maintainer) or an update branch plus a pull request (everyone else). It needs `git`, a remote the machine can reach, and credentials git already has (a credential helper, `gh auth login`, an SSH key); `gh` opens the pull request, and without it the branch is pushed and the PR is opened by hand. `update.transport: "email"` (or `EVERGREEN_UPDATE_TRANSPORT=email`) switches a machine to the email route below, where `evergreen.py notify` walks `notify.transports` and an agent takes over when the script reports "unsent". Evidence: [../RESEARCH.md](../RESEARCH.md) R-20260903-1 to R-20260903-5.

| Environment | Git route | Notes |
|---|---|---|
| Owner's machines (home PC, Mac) | maintainer: push to `master` | `gh auth login` once; the owner's editing clone stays quiet on the session-end hook (`notify.report_trunk`). |
| Corporate laptop with GitHub egress | contributor or maintainer, per the token | Sign in with a token scoped to the repo; if the proxy blocks git over HTTPS, fall back to email. |
| Someone else's machine (a share pack, a fork) | contributor: branch + pull request | Their `origin` is the fork; `git.upstream` names the trunk so the PR targets it. |
| Sandboxes with no outbound git | none | `EVERGREEN_UPDATE_TRANSPORT=email`, or leave the commits for the next `publish` from a connected machine. |

Email route (fallback), per environment:

| Environment | Unattended (script) | Agent-driven | Notes |
|---|---|---|---|
| Windows with classic Outlook signed in | `outlook` (COM via PowerShell) | | Fails cleanly where only the new Outlook exists (no COM object model). |
| Corporate Windows, new Outlook only | `graph` (Graph PowerShell SDK, delegated `Mail.Send`, cached token) | Chrome + Gmail compose URL, if personal Gmail is allowed | `Mail.Send` self-consent is Microsoft's 2026 default; a tenant can still block it. Corporate egress often blocks port 587, so `smtp` is a probe, not a plan. `mailto:` is unreliable with the new Outlook. |
| Home Windows, Linux, Mac | `smtp` (Gmail app password, 587 STARTTLS or 465) | Gmail connector (Cowork), Chrome + Drive picker | App passwords still exist for consumer Gmail (2-Step Verification required). Cowork runs no hooks: `checked` and the notify skill are the triggers there. |
| Sandboxes with no outbound SMTP | none | the session's mail tool | The bundle waits in the outbox; `outbox_copy_to` puts it in a synced folder when one is mounted. |

Hooks that fire the publisher (git route) or the mailer (email route): Claude Code `SessionEnd` (registered in `hooks/hooks.json`, detached: the 1.5 s default budget can be raised to 60 s with a per-hook `timeout`, but a push or a send must never block exit); Copilot CLI `sessionEnd` and Codex `SessionEnd` can call `scripts/evergreen-hook.sh end` the same way (add the entry by hand; both are short and synchronous, so keep the detach).

Hook that feeds the use log: Claude Code `PostToolUse` with matcher `Skill` runs `scripts/evergreen-hook.sh use`, which pipes the payload to `evergreen.py use-log` (silent; one JSON line per invocation in `EVERGREEN_HOME/uses.jsonl`). Codex `PostToolUse` carries `transcript_path` (with `turn_id`, `tool_use_id`, `tool_input`, `tool_response`), so the same script can feed the use log there once the field names are mapped; Copilot CLI `postToolUse` (`sessionId`, `toolName`, `toolArgs`, `toolResult`) has no transcript path, only `agentStop` does, so its row would log the invocation without one. Neither is wired yet (RESEARCH.md open questions).

## Snippets

`templates/AGENTS.md.snippet`, `templates/CLAUDE.md.snippet`, and `templates/copilot-instructions.md.snippet` are the blocks to paste into a repo to adopt evergreen there. They point at the preferences profile, the codemap store, and the "capture learnings, refresh when due" rules in about twenty lines.
