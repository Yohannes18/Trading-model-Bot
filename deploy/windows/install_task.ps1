$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe. Create .venv first."
}

$taskName = "QuantaraEngine"
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "-m quantara.main --all" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Installed scheduled task: $taskName"
