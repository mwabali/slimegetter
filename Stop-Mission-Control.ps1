$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "work\runtime-pids.json"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No launcher PID file exists. Nothing started by the launcher can be stopped safely."
    exit 0
}

$saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
foreach ($property in $saved.PSObject.Properties) {
    $process = Get-Process -Id ([int]$property.Value) -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Host "Stopped $($property.Name) (PID $($process.Id))"
    }
}
Remove-Item -LiteralPath $pidFile -Force
