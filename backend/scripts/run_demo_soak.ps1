param(
    [int]$Hours = 24,
    [string]$ApiBase = "http://127.0.0.1:8000/api/v1",
    [int]$IntervalSeconds = 300
)

$deadline = (Get-Date).ToUniversalTime().AddHours($Hours)
$failures = 0
while ((Get-Date).ToUniversalTime() -lt $deadline) {
    try {
        $status = Invoke-RestMethod -Uri "$ApiBase/system/status" -TimeoutSec 15
        if ($status.execution_enabled) { throw "Execution gate unexpectedly enabled" }
        if ($status.platform_mode -ne "READ_ONLY_SHADOW_MODE") { throw "Unexpected platform mode: $($status.platform_mode)" }
        Write-Output "$(Get-Date -Format o) OK MT5=$($status.mt5.state) worker=$($status.shadow_worker.state)"
    } catch {
        $failures++
        Write-Warning "$(Get-Date -Format o) soak failure ${failures}: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSeconds
}
if ($failures -gt 0) { exit 1 }
Write-Output "Demo soak completed successfully"
