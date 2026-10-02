---
name: clip-captioner
description: "Caption short video clips with the ClipCap service. Use when the user asks to caption a clip."
---

# Clip captioner

Fixture skill for the evergreen eval suite (case action-3). It needs an API token and a local model file; [SETUP.md](SETUP.md) lists both.

## Step 0

If this environment is not in `setup.envs` in `evergreen.json`, or a step fails for a missing piece, check `SETUP.md` first.

## Step 1

Send the clip to ClipCap with the token in `CLIPCAP_TOKEN` and the model at `~/.clipcap/model.bin`; write the captions next to the clip.
