# Runs the daily paper-portfolio workflow and logs output.
# Invoked by Windows Task Scheduler (see register_task.ps1).

# Resolve repo root = the parent of the scripts/ folder this file lives in.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"  # fall back to PATH if venv missing
}

# Per-day log file under logs/.
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "run-$Stamp.log"

"==== Run started $(Get-Date -Format o) ====" | Add-Content -Path $LogFile

# Quieten library deprecation warnings so a harmless stderr line isn't treated
# as a terminating error by PowerShell.
$env:PYTHONWARNINGS = "ignore"

# Run the workflow for today; merge stderr into stdout and append to the log.
& $Python -m market_journal.main --date today 2>&1 | Add-Content -Path $LogFile
$exit = $LASTEXITCODE

"==== Run finished $(Get-Date -Format o) (exit $exit) ====" | Add-Content -Path $LogFile
exit $exit
