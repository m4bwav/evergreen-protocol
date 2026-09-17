---
name: evergreen-pack
description: "Package the evergreen plugin into a single archive to email, back up, or install elsewhere: a versioned evergreen zip (folder inside, opens in 7-Zip or Explorer), an email-safe variant that Gmail accepts, and evergreen.plugin (flat, for Cowork's Save plugin button). Use on 'zip up evergreen', 'package the plugin', 'give me one file I can email myself', 'gmail blocked the zip', 'make a .plugin file', 'export evergreen for another machine', or 'bundle it for Copilot/Codex/Cursor' (which uses export instead of pack). No zipper to install: Python's built-in zip does it, with a PowerShell fallback."
---

# Evergreen pack

Since protocol 1.4 the normal install is a git clone of the trunk repository (README §Install, `templates/INSTALL-PROMPT-GIT.txt`) and updates travel by `publish` and `pull`; an archive is for Cowork's `.plugin`, a backup, a copy for someone without repository access, or the email fallback. One archive, no dependencies. Plugin root: two levels above this file (`${CLAUDE_SKILL_DIR}/../..` in Claude Code). `EG` below means `python "<plugin root>/scripts/evergreen.py"` with an absolute path.

## Step 0: freshness of this plugin (every use, one read)

Read `<plugin root>/evergreen.json`. If it is past `next_due`, say so and offer to refresh before packing, since an archive that ships stale research will be stale on arrival. Pack anyway if the user wants it now; the install audit catches it later.

## Step 1: pick the form

- Backup, another machine, Cowork: `EG pack [--out <dir>]` writes `evergreen-<version>.zip` (contains an `evergreen/` folder plus `INSTALL.txt` and `INSTALL-PROMPT.txt`), `evergreen-<version>-INSTALL-PROMPT.txt` beside it (the same prompt, ready to paste), and `evergreen.plugin` (same files, flat, the form Cowork's "Save plugin" button installs; Claude Code uses the folder, not this file). Default output: the folder next to the plugin. Both open in 7-Zip, Explorer, Finder, `unzip`.
- Email: `EG pack --mail` writes `evergreen-<version>-mail.zip` (plus the prompt file). Add `--split 24` when the route has a small per-attachment ceiling (a mail connector that moves attachments as base64 through the model, L-013): it also writes `.part01`, `.part02`, ... pieces of 24 KB that the prompt tells the recipient to join in order, one piece per message if need be. Gmail (and most corporate mail) rejects `.ps1` and other script types even inside a zip, so the mail form stores them as `name.ps1.txt`; INSTALL.txt inside tells the recipient to run `EG unmail evergreen` after unzipping (or rename by hand). The `.plugin` is left out of the mail form because it would be blocked the same way; `EG pack` rebuilds it on the other side. Alternative with no renaming: attach the normal zip from Google Drive (a Drive link is not scanned the same way).
- Someone else: `EG pack --share` (add `--mail` for email) writes `evergreen-<version>-share.zip`, `evergreen-share.plugin` and a matching prompt. It leaves out `profile/` (the user's preferences and environment facts) and ships an `evergreen.config.json` with no address and `notify.auto` off, so the recipient's install mails nobody until they set their own address, and it names their marketplace `my-local` so it never collides with the owner's. A share pack does not baseline this install, does not tag the trunk, and is not a report of anything: it is a copy to give away.
- A repo that other agents work in (Copilot, Codex, Cursor, Gemini): `EG export <repo>` copies the plugin into `<repo>/.agents/` with its layout intact, so the skills' relative links keep resolving. Then paste `templates/AGENTS.md.snippet` into the repo's `AGENTS.md`.

No Python on this machine? On Windows run `<plugin root>/scripts/pack.ps1` (uses the built-in `Compress-Archive`; or 7-Zip's `7z a` if installed). Elsewhere, `zip -r evergreen-<version>.zip evergreen -x "*__pycache__*" "*.pyc"` from the parent folder.

## Step 2: check the result

`EG pack` prints the paths and sizes. Confirm the zip has `evergreen/README.md`, `evergreen/MANIFEST.json`, `INSTALL.txt` and `INSTALL-PROMPT.txt` at the top, and no `__pycache__`. The prompt must read as one paste-and-go message with a single placeholder (the folder path); if the install steps change, edit `templates/INSTALL-PROMPT.txt`, never the recipient's instructions by hand (L-012). The normal archive carries the current `profile/` (the user's preferences and environment facts), so anything leaving the user's own machines uses `--share` instead; check a share archive has no `evergreen/profile/` entry and that its `evergreen.config.json` shows `"to": ""`.

Packing also: writes `MANIFEST.json` (file hashes and a `pack_id`) into the archive so installs can baseline themselves; takes the trunk's baseline from the shipped state; keeps a copy of the zip in `EVERGREEN_HOME/packs/` (the base a later merge may need); and, when the plugin folder is a git repo, commits any pending changes and tags `pack-<version>-<pack_id>` (`--no-git` skips that). The tag is what lets `git apply --3way` merge diverged files later.

## Step 3: hand over

One line with the path(s), and the sentence the recipient needs: save the files to one folder, paste `INSTALL-PROMPT.txt` into Claude Code with that folder's path in the placeholder. In Cowork, also present the `.plugin` file so it can be installed with one click. Bump `version` in `.claude-plugin/plugin.json` and log a `C-` entry when the packaged content changed since the last pack. On the receiving machine, the first `EG diff` (or `evergreen-audit`) baselines the pristine install from `MANIFEST.json`; if the files were edited before that, `EG baseline --from <this zip>`.

## Maintenance

This skill shares the plugin's unit: `evergreen.json` at the plugin root, [RESEARCH.md](../../RESEARCH.md), [CHANGELOG.md](../../CHANGELOG.md), [LEARNINGS.md](../../LEARNINGS.md), [TESTS.md](../../TESTS.md).
