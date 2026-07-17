param(
    [string]$TaskName = "XAUUSD Levi Daily Research Report",
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$Time = "00:30",
    [switch]$Commit
)

$backend = Join-Path $RepoRoot "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python venv not found at $python"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location -LiteralPath '$backend'; & '$python' -m app.reporting.levi_daily_report"
if ($Commit) {
    $arguments += " --commit"
}
$arguments += "`""

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Generate sanitized read-only Levi daily research reports." -Force | Out-Null
Write-Host "Installed scheduled task '$TaskName' at $Time. Trading workers are not started or controlled by this task."
