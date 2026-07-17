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
$env:XAU_KILL_SWITCH_ACTIVE = "false"

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
    demo = "app.workers.run_demo_loop"
    manager = "app.workers.run_demo_position_manager_loop"
    simulation = "app.workers.run_simulation_loop"
    strategy = "app.workers.run_strategy_shadow_loop"
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
Write-Host "Dashboard: http://127.0.0.1:5173"
Write-Host "API health: http://127.0.0.1:8000/api/v1/health"
