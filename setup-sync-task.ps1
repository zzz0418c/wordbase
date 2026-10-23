# Register a task that checks the vivo notes every 20 minutes (only acts 18:00-21:00).
# Run: powershell -ExecutionPolicy Bypass -File .\setup-sync-task.ps1

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot

$action = New-ScheduledTaskAction -Execute (Join-Path $dir "sync-check.cmd") -WorkingDirectory $dir

$once = New-ScheduledTaskTrigger -Once -At (Get-Date).Date
$once.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 20) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "vocabcurve-sync-vivo" -Action $action -Trigger $once `
    -Settings $settings -Description "scan vivo notes 18-21, update progress, push" -Force | Out-Null

Write-Host "OK: vocabcurve-sync-vivo registered (every 20 min, active 18:00-21:00)"
Get-ScheduledTaskInfo -TaskName "vocabcurve-sync-vivo" | Select-Object NextRunTime
