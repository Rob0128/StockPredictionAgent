<#
.SYNOPSIS
    Registers a Windows Scheduled Task that runs the daily paper-portfolio
    workflow on weekdays at a chosen local time.

.EXAMPLE
    # Default: weekdays at 21:30 local time (after US close for UK users)
    .\scripts\register_task.ps1

.EXAMPLE
    # Custom time
    .\scripts\register_task.ps1 -Time "16:35"

.NOTES
    Re-run this script to update the schedule. Remove with:
        Unregister-ScheduledTask -TaskName "MarketJournalDaily" -Confirm:$false
#>
param(
    [string]$Time = "21:30",                 # local HH:mm; 21:30 BST ~= 16:30 ET
    [string]$TaskName = "MarketJournalDaily"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RunScript = Join-Path $Root "scripts\run_daily.ps1"
if (-not (Test-Path $RunScript)) {
    throw "Cannot find run_daily.ps1 at $RunScript"
}

# Action: run PowerShell hidden, executing the run script.
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`""

# Trigger: weekly, Monday-Friday, at the chosen time.
$Trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $Time

# Run whether or not the user is logged on is NOT used here so it can run as the
# current interactive user (keeps access to the venv + .env). Wake the machine
# if asleep, and still run if a scheduled start was missed (laptop was off).
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily paper-portfolio market research journal (local run)." `
    -Force | Out-Null

Write-Host "Registered task '$TaskName' to run weekdays at $Time (local)."
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "View it:             Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Logs:                $Root\logs\run-<date>.log"
Write-Host "Remove it:           Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
