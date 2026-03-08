$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$scriptPath = Join-Path $projectRoot "deploy\windows\rotate_logs.ps1"

if (-not (Test-Path $scriptPath)) {
    throw "rotate_logs.ps1 not found at $scriptPath"
}

$taskName = "QuantaraLogCleanup"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At 03:00AM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Installed scheduled task: $taskName"
