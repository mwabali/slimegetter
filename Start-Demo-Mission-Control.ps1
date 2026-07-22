$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$work = Join-Path $root "work"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$node = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
$vite = Join-Path $root "frontend\node_modules\vite\bin\vite.js"
$pidFile = Join-Path $work "runtime-pids.json"

New-Item -ItemType Directory -Path $work -Force | Out-Null
if (-not (Test-Path -LiteralPath $python)) { throw "Project Python environment was not found: $python" }
if (-not (Test-Path -LiteralPath $node)) { throw "Bundled Node.js was not found: $node" }
if (-not (Test-Path -LiteralPath $vite)) { throw "Dashboard dependencies are missing. Run pnpm install in frontend." }

$terminalCandidates = @(
    (Join-Path $env:ProgramFiles "MetaTrader 5\terminal64.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "MetaTrader 5\terminal64.exe")
) | Where-Object { Test-Path -LiteralPath $_ }
if (-not $terminalCandidates) {
    throw "MetaTrader 5 terminal64.exe was not found. Install MT5 and log into a DEMO account first."
}

$env:PYTHONPATH = Join-Path $root "backend"
$env:XAU_TRADING_MODE = "demo"
$env:XAU_EXECUTION_ENABLED = "true"
$env:XAU_DEMO_TRADING_CONFIRMED = "true"
$env:XAU_DEMO_OVERRIDE_WEEKLY_LOSS_STOP = "true"
# Temporary demo-only override for today's scheduled 03:00-06:00 EAT window.
# It expires automatically at 03:00 UTC and does not bypass HALTED/UNKNOWN states.
$env:XAU_DEMO_OVERRIDE_DEFENSIVE_COOLDOWN_UNTIL = "2026-07-22T03:00:00Z"
$env:XAU_KILL_SWITCH_ACTIVE = "false"
$env:XAU_MT5_SERVER_UTC_OFFSET_HOURS = "3"
$env:XAU_NEWS_PROVIDER = "manual"
$env:XAU_MANUAL_CALENDAR_PATH = "data/verified_events.json"
$env:XAU_DEMO_SESSION_WINDOWS = "03:00-06:00,06:00-08:00,10:00-12:00,14:00-17:00"
$env:XAU_DEMO_ENTRY_ENABLED = "true"
$env:XAU_DEMO_ENTRY_POLL_SECONDS = "5"
$env:XAU_DEMO_EXPLORATION_ENABLED = "true"
$env:XAU_DEMO_EXPLORATION_MIN_MARKET_QUALITY = "4.0"
$env:XAU_DEMO_POSITION_MANAGER_ENABLED = "true"
$env:XAU_DEMO_POSITION_POLL_SECONDS = "1"
$env:XAU_DEMO_POSITION_EXIT_POLICY = "HYBRID_PROFIT_PROTECTION"
$env:XAU_DEMO_POSITION_CLOSE_ON_OPPOSITE_SIGNAL = "false"
$env:XAU_DEMO_POSITION_FAILED_PROTECTION_RETRY_SECONDS = "15"
$env:XAU_DEMO_POSITION_MARKET_CLOSED_COOLDOWN_MINUTES = "180"
$env:XAU_DEMO_POSITION_TRAILING_ACTIVATION_USD = "0.50"
$env:XAU_DEMO_POSITION_TRAILING_GIVEBACK_USD = "0.30"
$env:XAU_DEMO_POSITION_TRAILING_GIVEBACK_PCT = "0.35"

if ($env:XAU_EXECUTION_ENABLED -eq "true" -and $env:XAU_DEMO_POSITION_MANAGER_ENABLED -ne "true") {
    throw "Refusing demo execution while XAU_DEMO_POSITION_MANAGER_ENABLED is not true."
}

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Start-HiddenProcess([string]$Name, [string]$File, [string[]]$Arguments, [string]$WorkingDirectory) {
    $out = Join-Path $work "$Name-current.out.log"
    $err = Join-Path $work "$Name-current.err.log"
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
    Write-Host "Started $Name (PID $($process.Id))"
    return $process.Id
}

$pids = [ordered]@{}
if (Test-Port 8000) {
    Write-Host "API is already listening on port 8000"
} else {
    $pids.api = Start-HiddenProcess "api" $python @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") $backend
}

$workers = @{
    manager = "app.workers.run_demo_position_manager_loop"
    simulation = "app.workers.run_simulation_loop"
    strategy = "app.workers.run_strategy_shadow_loop"
}
if ($env:XAU_DEMO_ENTRY_ENABLED -eq "true") {
    $workers.demo = "app.workers.run_demo_loop"
} else {
    Write-Host "Demo entry worker disabled for position-manager validation."
}
foreach ($name in $workers.Keys) {
    $module = $workers[$name]
    $alreadyRunning = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$module*" } | Select-Object -First 1
    if ($alreadyRunning) {
        Write-Host "$name worker is already running (PID $($alreadyRunning.ProcessId))"
    } else {
        $pids[$name] = Start-HiddenProcess $name $python @("-m", $module) $backend
    }
}

if (Test-Port 5173) {
    Write-Host "Dashboard is already listening on port 5173"
} else {
    $pids.dashboard = Start-HiddenProcess "dashboard" $node @($vite, "--host", "127.0.0.1", "--port", "5173") (Join-Path $root "frontend")
}

$pids | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:5173"
Write-Host "Mission Control is starting in GUARDED DEMO EXECUTION MODE."
Write-Host "Pixis close manager: enabled=$env:XAU_DEMO_POSITION_MANAGER_ENABLED policy=$env:XAU_DEMO_POSITION_EXIT_POLICY poll=${env:XAU_DEMO_POSITION_POLL_SECONDS}s oppositeSignal=$env:XAU_DEMO_POSITION_CLOSE_ON_OPPOSITE_SIGNAL trailingActivation=$env:XAU_DEMO_POSITION_TRAILING_ACTIVATION_USD givebackUsd=$env:XAU_DEMO_POSITION_TRAILING_GIVEBACK_USD givebackPct=$env:XAU_DEMO_POSITION_TRAILING_GIVEBACK_PCT"
Write-Host "Demo entry worker enabled: $env:XAU_DEMO_ENTRY_ENABLED"
Write-Host "Dashboard: http://127.0.0.1:5173"
Write-Host "API health: http://127.0.0.1:8000/api/v1/health"
