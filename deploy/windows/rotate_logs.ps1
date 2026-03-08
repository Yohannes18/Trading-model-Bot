$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$logDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$now = Get-Date -Format "yyyyMMdd-HHmmss"
$mainLog = Join-Path $logDir "jeafx.log"
$errorLog = Join-Path $logDir "jeafx.error.log"

if (Test-Path $mainLog) {
    Move-Item $mainLog (Join-Path $logDir "jeafx.$now.log") -Force
}
if (Test-Path $errorLog) {
    Move-Item $errorLog (Join-Path $logDir "jeafx.error.$now.log") -Force
}

Get-ChildItem $logDir -Filter "jeafx*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 |
    Remove-Item -Force

Write-Host "Log rotation complete."
