# Setup: clip-captioner

What [SKILL.md](SKILL.md) needs outside itself.

## Needs

| id | kind | check | for | if missing |
|---|---|---|---|---|
| clipcap-token | env | `CLIPCAP_TOKEN` | authenticating to the ClipCap captioning service in Step 1 | required |
| clipcap-model | file | `~/.clipcap/model.bin` | the local speech model ClipCap aligns captions with | required |

## Install

### clipcap-token

- any: sign in at the ClipCap dashboard, create a token, set it as `CLIPCAP_TOKEN` in your shell profile (manual, secret)

## Environments met

| date | os | harness | missing | notes |
|---|---|---|---|---|
