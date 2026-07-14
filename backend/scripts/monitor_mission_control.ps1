param(
    [string]$ApiBase = "http://127.0.0.1:8000/api/v1",
    [int]$IntervalSeconds = 60,
    [string]$LogPath = "$PSScriptRoot\..\outputs\mission-control-health.jsonl"
)

$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
while ($true) {
    try {
        $health = Invoke-RestMethod -Uri "$ApiBase/system/status" -TimeoutSec 15
        $record = [ordered]@{ timestamp = (Get-Date).ToUniversalTime().ToString("o"); mt5 = $health.mt5.state; worker = $health.shadow_worker.state; news = $health.news.state; execution_enabled = $health.execution_enabled }
        ($record | ConvertTo-Json -Compress) | Add-Content -LiteralPath $LogPath
        if ($health.execution_enabled) { Write-Error "Execution must remain disabled" }
    } catch {
        $record = [ordered]@{ timestamp = (Get-Date).ToUniversalTime().ToString("o"); error = $_.Exception.Message }
        ($record | ConvertTo-Json -Compress) | Add-Content -LiteralPath $LogPath
    }
    Start-Sleep -Seconds $IntervalSeconds
}
