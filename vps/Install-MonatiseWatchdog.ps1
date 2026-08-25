param(
    [string]$ScriptPath = "C:\Monatise\MonatiseMT5Watchdog.ps1"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ScriptPath)) {
    throw "Watchdog script not found: $ScriptPath"
}

$action = New-ScheduledTaskAction `
    -Execute "PowerShell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$startup = New-ScheduledTaskTrigger -AtStartup
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName "Monatise MT5 Watchdog" `
    -Action $action `
    -Trigger @($startup, $repeat) `
    -Settings $settings `
    -User "SYSTEM" `
    -RunLevel Highest `
    -Force | Out-Null

Write-Output "Installed scheduled task: Monatise MT5 Watchdog"
