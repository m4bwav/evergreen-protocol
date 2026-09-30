#!/bin/sh
# Claude Code hooks. Fail-silent by design; never blocks a session.
#   SessionStart (no argument): print stale evergreen units into context. Prints nothing when nothing is due.
#   SessionEnd   (argument "end"): hand the self-update to a detached background process
#                (`notify --if-changed --from-hook --detach`: with update.transport git that is `publish`, a commit and
#                push to the trunk repository or an update branch + PR; with email, the mailer) because SessionEnd
#                hooks share a 1.5 s budget.
#   PostToolUse  (argument "use", matcher Skill): append the Skill invocation from the JSON payload on stdin to
#                EVERGREEN_HOME/uses.jsonl (`use-log`). Prints nothing: PostToolUse stdout can reach the model.
#   PostToolUse  (argument "worth", matcher Write|Edit|MultiEdit): when the edited file is a SKILL.md, run the
#                static worth check (`worth-hook`) and, once per warning per session, hand the model a short warning
#                as additionalContext. Any other file returns before Python starts.
# Windows (Git Bash): ${CLAUDE_PLUGIN_ROOT} may arrive with backslashes, and `python3` is often the Store stub.
if [ "$1" = "worth" ]; then  # the fast path: most edits are not to a SKILL.md, so decide before probing for Python
  payload=$(cat)
  case "$payload" in *SKILL.md*) ;; *) exit 0 ;; esac
fi
self=$(printf '%s' "$0" | tr '\\' '/')
DIR="$(cd "$(dirname "$self")" && pwd)"
# A candidate counts only if it can actually run Python: the Windows Store stub and the macOS Command Line
# Tools stub both exist on PATH and fail (or pop a dialog) instead of running a script.
PY=""
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) CANDS="py -3|python|python3" ;;
  *)                    CANDS="python3|python" ;;
esac
old_ifs=$IFS; IFS='|'
for c in $CANDS; do
  if $c -c "import sys" >/dev/null 2>&1; then PY=$c; break; fi
done
IFS=$old_ifs
[ -z "$PY" ] && exit 0
if [ "$1" = "end" ]; then
  $PY "$DIR/evergreen.py" notify --if-changed --from-hook --detach >/dev/null 2>&1
  exit 0
fi
if [ "$1" = "worth" ]; then
  printf '%s' "$payload" | $PY "$DIR/evergreen.py" worth-hook 2>/dev/null
  exit 0
fi
if [ "$1" = "use" ]; then
  $PY "$DIR/evergreen.py" use-log >/dev/null 2>&1   # stdin (the hook payload) passes straight through
  exit 0
fi
$PY "$DIR/evergreen.py" audit --brief 2>/dev/null
exit 0
