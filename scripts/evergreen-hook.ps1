# Claude Code hooks, PowerShell variant for Windows setups that run hooks through powershell.exe. Fail-silent.
#   no argument : SessionStart, prints stale evergreen units into context (nothing when nothing is due)
#   -End        : SessionEnd, hands the update digest to a detached background process (1.5 s hook budget)
#   -Use        : PostToolUse (matcher Skill), forwards the JSON payload on stdin to `use-log`, which appends the
#                 Skill invocation to EVERGREEN_HOME\uses.jsonl; prints nothing (PostToolUse stdout can reach the model)
# settings.json example:
#   "SessionStart": [{"hooks": [{"type": "command",
#     "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<plugin>\\scripts\\evergreen-hook.ps1\"", "timeout": 15}]}],
#   "SessionEnd":   [{"hooks": [{"type": "command",
#     "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<plugin>\\scripts\\evergreen-hook.ps1\" -End", "timeout": 5}]}],
#   "PostToolUse":  [{"matcher": "Skill", "hooks": [{"type": "command",
#     "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<plugin>\\scripts\\evergreen-hook.ps1\" -Use", "timeout": 5}]}]
param([switch]$End, [switch]$Use)
try {
  $dir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $py = $null
  foreach ($c in @("py", "python", "python3")) {  # probe: the Store stub is on PATH but cannot run a script
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { continue }
    $probe = if ($c -eq "py") { @("-3", "-c", "import sys") } else { @("-c", "import sys") }
    & $c @probe 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
  }
  if (-not $py) { exit 0 }
  $pyArgs = @()
  if ($py -eq "py") { $pyArgs += "-3" }
  if ($End) {
    $pyArgs += @((Join-Path $dir "evergreen.py"), "notify", "--if-changed", "--from-hook", "--detach")
    & $py @pyArgs 2>$null | Out-Null
  } elseif ($Use) {
    $pyArgs += @((Join-Path $dir "evergreen.py"), "use-log")
    $input | & $py @pyArgs 2>$null | Out-Null
  } else {
    $pyArgs += @((Join-Path $dir "evergreen.py"), "audit", "--brief")
    & $py @pyArgs 2>$null
  }
} catch {}
exit 0
