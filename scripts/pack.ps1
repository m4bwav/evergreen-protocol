# pack.ps1 - build evergreen-<version>.zip and evergreen.plugin without Python.
# Uses 7-Zip if present (7z.exe on PATH or in Program Files), else Windows' built-in Compress-Archive.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pack.ps1 [-Out <dir>]
param([string]$Out = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$manifest = Get-Content (Join-Path $root ".claude-plugin\plugin.json") -Raw | ConvertFrom-Json
$ver = if ($manifest.version) { $manifest.version } else { "0.0.0" }
if (-not $Out) { $Out = Split-Path -Parent $root }
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("evergreen-pack-" + [guid]::NewGuid().ToString("N"))
$stageRoot = Join-Path $stage "evergreen"
$excludeDirs = @(".git", "__pycache__", "node_modules", ".pytest_cache")
$excludeFiles = @("*.pyc", "*.zip", "*.plugin", "*.7z", ".DS_Store")

function Copy-Tree([string]$src, [string]$dst) {
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  foreach ($item in Get-ChildItem -Path $src -Force) {
    if ($item.PSIsContainer) {
      if ($excludeDirs -contains $item.Name) { continue }
      Copy-Tree $item.FullName (Join-Path $dst $item.Name)
    } else {
      $skip = $false
      foreach ($pat in $excludeFiles) { if ($item.Name -like $pat) { $skip = $true; break } }
      if (-not $skip) { Copy-Item $item.FullName (Join-Path $dst $item.Name) -Force }
    }
  }
}

try {
  Copy-Tree $root $stageRoot
  @"
Evergreen $ver (self-maintaining skills for AI agents)

Unzip anywhere (7-Zip, Explorer, unzip), then read evergreen\README.md > Install.
Quick paths: Claude Code `claude plugin install <folder>`; Cowork: install the .plugin file;
other agents: `python evergreen\scripts\evergreen.py export <repo>` copies it into <repo>\.agents\.
First run: the evergreen-audit skill (checks whether this copy went stale on the shelf).
"@ | Set-Content -Path (Join-Path $stage "INSTALL.txt") -Encoding UTF8

  $zip = Join-Path $Out "evergreen-$ver.zip"
  $plugin = Join-Path $Out "evergreen.plugin"
  Remove-Item $zip, $plugin -Force -ErrorAction SilentlyContinue

  $sevenZip = $null
  foreach ($c in @("7z", "$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $sevenZip = $c; break }
    if (Test-Path $c) { $sevenZip = $c; break }
  }
  if ($sevenZip) {
    & $sevenZip a -tzip -mx=5 $zip (Join-Path $stage "*") | Out-Null
    & $sevenZip a -tzip -mx=5 $plugin (Join-Path $stageRoot "*") | Out-Null
  } else {
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
    # Compress-Archive insists on a .zip extension; build then rename.
    $tmpPlugin = Join-Path $Out "evergreen.plugin.zip"
    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $tmpPlugin -Force
    Move-Item $tmpPlugin $plugin -Force
  }
  Write-Output "wrote $zip"
  Write-Output "wrote $plugin"
} finally {
  if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
