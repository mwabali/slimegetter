param(
    [string]$Database = "$PSScriptRoot\..\xauusd.db",
    [string]$Destination = "$PSScriptRoot\..\backups"
)

$resolvedDatabase = (Resolve-Path -LiteralPath $Database).Path
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path (Resolve-Path -LiteralPath $Destination) "xauusd-$stamp.db"
Copy-Item -LiteralPath $resolvedDatabase -Destination $target -Force
Write-Output "Backup created: $target"
