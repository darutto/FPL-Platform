# capture.ps1 — run the fpl-historical capture CLI with PYTHONPATH wired.
#
# Usage (from anywhere):
#   packages\fpl-historical\capture.ps1 capture --season 2025-2026
#   packages\fpl-historical\capture.ps1 capture --skip-if-fresh 24
#   packages\fpl-historical\capture.ps1 capture-gw --current
#   packages\fpl-historical\capture.ps1 capture-gw --gw 36 --force
#   packages\fpl-historical\capture.ps1 capture-gw --auto
#
# The subcommand (capture / capture-gw) is passed through from args.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

if (Test-Path "$RepoRoot\.venv\Scripts\python.exe") {
    $Py = "$RepoRoot\.venv\Scripts\python.exe"
} elseif (Test-Path "$RepoRoot\.venv\bin\python") {
    $Py = "$RepoRoot\.venv\bin\python"
} else {
    $Py = "python"
}

$env:PYTHONPATH = "$RepoRoot\packages\fpl-historical;$RepoRoot\packages\fpl-api-client"
if ($env:PYTHONPATH_ORIG) { $env:PYTHONPATH = "$env:PYTHONPATH;$env:PYTHONPATH_ORIG" }

& $Py -m fpl_historical.cli @args
exit $LASTEXITCODE
