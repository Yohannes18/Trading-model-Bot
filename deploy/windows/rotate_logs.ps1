$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$logDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$now = Get-Date -Format "yyyyMMdd-HHmmss"
$mainLog = Join-Path $logDir "quantara.log"
$errorLog = Join-Path $logDir "quantara.error.log"

if (Test-Path $mainLog) {
    Move-Item $mainLog (Join-Path $logDir "quantara.$now.log") -Force
}
if (Test-Path $errorLog) {
    Move-Item $errorLog (Join-Path $logDir "quantara.error.$now.log") -Force
}

Get-ChildItem $logDir -Filter "quantara*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 |
    Remove-Item -Force

Write-Host "Log rotation complete."
