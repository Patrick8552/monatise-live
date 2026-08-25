param(
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$LogPath = "C:\Monatise\watchdog.log"
)

$ErrorActionPreference = "Stop"
$logDirectory = Split-Path -Parent $LogPath
if (-not (Test-Path $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}

function Write-WatchdogLog([string]$Message) {
    $line = "{0:o} {1}" -f [DateTime]::UtcNow, $Message
    Add-Content -Path $LogPath -Value $line
}

if (-not (Test-Path $TerminalPath)) {
    Write-WatchdogLog "ERROR terminal64.exe is absent at the configured path"
    exit 2
}

$terminal = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
if ($null -eq $terminal) {
    Start-Process -FilePath $TerminalPath
    Write-WatchdogLog "RECOVERY started terminal64.exe"
    exit 1
}

Write-WatchdogLog "OK terminal64.exe running pid=$($terminal.Id -join ',')"
exit 0
