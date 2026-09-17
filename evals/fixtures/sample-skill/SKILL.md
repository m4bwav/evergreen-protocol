---
name: sample-skill
description: "A fixture for the evergreen plugin's own test cases: writes a one-line marker file when asked to 'leave a marker' or 'stamp this folder'. Not a real skill; do not install it."
---

# sample-skill

Leave a marker file the caller can check.

## Step 1: write the marker

Write `MARKER.txt` in the folder the user names, containing today's date and the word `stamped`. Confirm the file exists by reading it back before reporting done; the reply is not the evidence, the file is.

## Output

One line: the path of the marker.
