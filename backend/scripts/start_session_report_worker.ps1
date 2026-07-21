param([int]$IntervalSeconds = 300)

$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Missing Python runtime: $python" }

$env:PYTHONPATH = $backend
$env:XAU_TRADING_MODE = "demo"
$env:XAU_EXECUTION_ENABLED = "false"
$env:XAU_DEMO_TRADING_CONFIRMED = "false"

Start-Process -FilePath $python `
    -ArgumentList @("-m", "app.workers.run_session_report_loop") `
    -WorkingDirectory $backend `
    -WindowStyle Hidden

Write-Host "Read-only session report worker started. Interval: $IntervalSeconds seconds."
