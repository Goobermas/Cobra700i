<#
  Request a graceful stop of the KaLab analysis worker.

  The worker checks for stop.request between work items and exits at a checkpoint.
  This script never kills arbitrary java.exe processes: it only signals the PID
  recorded in out/ghidra/.analysis.lock, and only after confirming that PID is
  the harness we started.
#>
[CmdletBinding()]
param([switch]$Force)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Get-Content (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
$out = if ([System.IO.Path]::IsPathRooted($cfg.out_dir)) {
    $cfg.out_dir
} else {
    Join-Path $root $cfg.out_dir
}
$lockPath = Join-Path $out '.analysis.lock'
$stopPath = Join-Path $out '.stop.request'

if (-not (Test-Path $lockPath)) {
    Write-Host "No active worker (no lock file). Nothing to stop." -ForegroundColor Yellow
    exit 0
}

$lock = Get-Content $lockPath -Raw | ConvertFrom-Json
$pidNum = [int]$lock.pid
Write-Host "Worker pid $pidNum (host $($lock.host), started $($lock.started))"

New-Item -ItemType File -Path $stopPath -Force | Out-Null
Write-Host "Wrote stop request: $stopPath"
Write-Host "The worker will finish its current item and exit at the next checkpoint."

if ($Force) {
    if ($lock.host -ne [System.Net.Dns]::GetHostName()) {
        throw 'Refusing to terminate a process recorded on a different host.'
    }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $pidNum" -ErrorAction SilentlyContinue
    if ($proc -and $proc.Name -match '^python(?:w|\d+(?:\.\d+)?)?\.exe$' -and
            $proc.CommandLine -like '*tools*analysis*controller.py*' -and
            $proc.CommandLine -like "*$root*") {
        Write-Host "Force: stopping verified KaLab controller process $pidNum" -ForegroundColor Yellow
        Stop-Process -Id $pidNum -ErrorAction Stop
    } else {
        throw 'PID does not belong to the expected KaLab controller. Stop request remains pending.'
    }
}
exit 0
