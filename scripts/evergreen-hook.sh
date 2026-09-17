#!/bin/sh
# Claude Code hooks. Fail-silent by design; never blocks a session.
#   SessionStart (no argument): print stale evergreen units into context. Prints nothing when nothing is due.
#   SessionEnd   (argument "end"): hand the self-update to a detached background process
#                (`notify --if-changed --from-hook --detach`: with update.transport git that is `publish`, a commit and
#                push to the trunk repository or an update branch + PR; with email, the mailer) because SessionEnd
#                hooks share a 1.5 s budget.
#   PostToolUse  (argument "use", matcher Skill): append the Skill invocation from the JSON payload on stdin to
#                EVERGREEN_HOME/uses.jsonl (`use-log`). Prints nothing: PostToolUse stdout can reach the model.
# Windows (Git Bash): ${CLAUDE_PLUGIN_ROOT} may arrive with backslashes, and `python3` is often the Store stub.
self=$(printf '%s' "$0" | tr '\\' '/')
DIR="$(cd "$(dirname "$self")" && pwd)"
PY=""
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v py >/dev/null 2>&1; then PY="py -3"
    elif command -v python >/dev/null 2>&1; then PY=python
    elif command -v python3 >/dev/null 2>&1; then PY=python3
    fi ;;
  *)
    if command -v python3 >/dev/null 2>&1; then PY=python3
    elif command -v python >/dev/null 2>&1; then PY=python
    fi ;;
esac
[ -z "$PY" ] && exit 0
if [ "$1" = "end" ]; then
  $PY "$DIR/evergreen.py" notify --if-changed --from-hook --detach >/dev/null 2>&1
  exit 0
fi
if [ "$1" = "use" ]; then
  $PY "$DIR/evergreen.py" use-log >/dev/null 2>&1   # stdin (the hook payload) passes straight through
  exit 0
fi
$PY "$DIR/evergreen.py" audit --brief 2>/dev/null
exit 0
