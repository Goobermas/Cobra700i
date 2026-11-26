<#
  Verify a KaLab package directory (or an extracted ZIP) before use.

  Checks: required files, config parse, no firmware / binaries, checkpoint
  readability, and that launchers reference only relative paths.
#>
[CmdletBinding()]
param([string]$Path)

$ErrorActionPreference = 'Stop'
if (-not $Path) { $Path = Split-Path -Parent $MyInvocation.MyCommand.Path }
$root = (Resolve-Path $Path).Path
$fail = 0

function Check([string]$label, [bool]$ok, [string]$detail = '') {
    if ($ok) { Write-Host "OK    $label $detail" -ForegroundColor Green }
    else     { Write-Host "FAIL  $label $detail" -ForegroundColor Red; $script:fail++ }
}

Write-Host "Verifying $root"

$required = @(
    'run_analysis.ps1', 'stop_analysis.ps1', 'verify_package.ps1',
    'config.example.json', 'tools\analysis\harness.py',
    'tools\ghidra_scripts\Export.java', 'README_WINDOWS.md'
)
foreach ($f in $required) {
    Check "file $f" (Test-Path (Join-Path $root $f))
}

$cfgFile = Join-Path $root 'config.example.json'
if (Test-Path $cfgFile) {
    try { $null = Get-Content $cfgFile -Raw | ConvertFrom-Json; Check 'config.example.json parses' $true }
    catch { Check 'config.example.json parses' $false $_.Exception.Message }
}

# firmware / binary leakage
$bad = Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue |
       Where-Object { $_.Extension -in '.bin', '.mot', '.s', '.srec', '.sla', '.zip', '.jar' }
Check 'no firmware/binary payloads' ($bad.Count -eq 0) (($bad | ForEach-Object { $_.Name }) -join ', ')

# absolute-path leakage in launchers
foreach ($ps in @('run_analysis.ps1', 'stop_analysis.ps1')) {
    $p = Join-Path $root $ps
    if (Test-Path $p) {
        $hits = Select-String -Path $p -Pattern 'C:\\Users\\|/workspace/|/home/' -ErrorAction SilentlyContinue
        Check "$ps has no hardcoded absolute paths" ($null -eq $hits)
    }
}

# checkpoint integrity
$q = Join-Path $root 'out\ghidra\workqueue.json'
if (Test-Path $q) {
    try {
        $data = Get-Content $q -Raw | ConvertFrom-Json
        $n = @($data.items).Count
        $done = @($data.items | Where-Object { $_.status -eq 'DONE' }).Count
        Check "workqueue readable ($done/$n done)" $true
    } catch { Check 'workqueue readable' $false $_.Exception.Message }
} else {
    Write-Host "INFO  no workqueue yet (fresh install)" -ForegroundColor Yellow
}

# python present
$py = Get-Command python -ErrorAction SilentlyContinue
Check 'python on PATH' ([bool]$py)

Write-Host ""
if ($fail -eq 0) { Write-Host "PACKAGE OK" -ForegroundColor Green; exit 0 }
Write-Host "$fail check(s) failed" -ForegroundColor Red
exit 1
