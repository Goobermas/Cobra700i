<#
  KaLab overnight research launcher (Windows 11 / PowerShell 5.1+)

  .EXAMPLE
    .\run_analysis.ps1 -DryRun
    .\run_analysis.ps1 -RunOnce
    .\run_analysis.ps1 -MaxHours 8
    .\run_analysis.ps1 -Resume
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$RunOnce,
    [double]$MaxHours = 0,
    [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $root 'config.json'
$problems = New-Object System.Collections.Generic.List[string]
$checks  = New-Object System.Collections.Generic.List[string]

function Add-Check([string]$name, [bool]$ok, [string]$detail = '') {
    if ($ok) { $checks.Add("OK    $name $detail") }
    else     { $problems.Add("FAIL  $name $detail"); $checks.Add("FAIL  $name $detail") }
}

Write-Host "KaLab launcher - $root" -ForegroundColor Cyan

# ---- 1. Python -------------------------------------------------------------
$py = $null
foreach ($cand in @('python', 'python3', 'py')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
Add-Check 'Python 3' ([bool]$py) $(if ($py) { $py } else { 'not found on PATH' })
if ($py) {
    $ver = & $py --version 2>&1
    Add-Check 'Python version' ($ver -match '3\.(9|1[0-9])') $ver
}

# ---- 2. config -------------------------------------------------------------
if (-not (Test-Path $configPath)) {
    Write-Host "Creating config.json from config.example.json" -ForegroundColor Yellow
    Copy-Item (Join-Path $root 'config.example.json') $configPath
}
try {
    $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
    Add-Check 'config.json parses' $true
} catch {
    Add-Check 'config.json parses' $false $_.Exception.Message
    $cfg = $null
}

function Resolve-Rel([string]$p) {
    if (-not $p) { return '' }
    if ([System.IO.Path]::IsPathRooted($p)) { return $p }
    return (Join-Path $root $p)
}

if ($cfg) {
    # ---- 3. JDK 21 ---------------------------------------------------------
    $javaExe = $null
    if ($cfg.java_home) {
        $candidate = Join-Path (Resolve-Rel $cfg.java_home) 'bin\java.exe'
        if (Test-Path $candidate) { $javaExe = $candidate }
    }
    if (-not $javaExe -and $env:JAVA_HOME) {
        $candidate = Join-Path $env:JAVA_HOME 'bin\java.exe'
        if (Test-Path $candidate) { $javaExe = $candidate }
    }
    if (-not $javaExe) {
        $j = Get-Command java -ErrorAction SilentlyContinue
        if ($j) { $javaExe = $j.Source }
    }
    Add-Check 'java.exe' ([bool]$javaExe) ($(if ($javaExe) { $javaExe } else { 'set java_home in config.json' }))
    if ($javaExe) {
        $jv = & $javaExe -version 2>&1 | Out-String
        $major = if ($jv -match 'version "(\d+)') { $Matches[1] } else { '?' }
        Add-Check 'JDK major version' ($major -eq '21') "found $major (Ghidra 11.4.2 expects 21)"
    }

    # ---- 4. Ghidra ---------------------------------------------------------
    $ghidra = Resolve-Rel $cfg.ghidra_home
    $headless = if ($ghidra) { Join-Path $ghidra 'support\analyzeHeadless.bat' } else { '' }
    Add-Check 'analyzeHeadless.bat' ([bool]($headless -and (Test-Path $headless))) $headless
    if ($headless -and (Test-Path $headless)) {
        $propsOk = $false
        $props = Join-Path $ghidra 'Ghidra\application.properties'
        if (Test-Path $props) {
            $line = Select-String -Path $props -Pattern '^application.version=' | Select-Object -First 1
            Add-Check 'Ghidra version 11.4.2' ($line -and $line.Line -match '11\.4\.2') $line.Line
        }

        # ---- 5. RXv3 language ---------------------------------------------
        $rxDir = Join-Path $ghidra 'Ghidra\Extensions\RX\data\languages'
        $ldefs = Join-Path $rxDir 'rx.ldefs'
        Add-Check 'RX extension rx.ldefs' (Test-Path $ldefs) $ldefs
        if (Test-Path $ldefs) {
            $hasV3 = (Select-String -Path $ldefs -Pattern 'RX:LE:32:RXv3' -Quiet)
            Add-Check 'RX:LE:32:RXv3 declared' $hasV3
            foreach ($sla in @('rx_v1.sla', 'rx_v2.sla', 'rx_v3.sla')) {
                Add-Check "compiled $sla" (Test-Path (Join-Path $rxDir $sla)) (Join-Path $rxDir $sla)
            }
        }
    }

    # ---- 6. inputs ---------------------------------------------------------
    $fw = Resolve-Rel $cfg.firmware
    Add-Check 'firmware image' (Test-Path $fw) $fw
    if (Test-Path $fw) {
        $len = (Get-Item $fw).Length
        Add-Check 'firmware size 1 MiB' ($len -eq 1048576) "$len bytes"
    }
    $proj = Resolve-Rel $cfg.project_dir
    Add-Check 'Ghidra project dir' (Test-Path $proj) $proj
    $fcs = Resolve-Rel $cfg.functions_csv
    Add-Check 'functions.csv' (Test-Path $fcs) $fcs
    if ((Test-Path $fcs) -and (Test-Path $fw)) {
        $sample = (Get-Content $fcs -TotalCount 2)[1].Split(',')[0]
        Add-Check 'sample function address' ($sample -match '^0x?fff') $sample
    }

    # ---- 7. outputs --------------------------------------------------------
    foreach ($d in @('logs', 'logs\sessions', 'results', 'results\checkpoints',
                     'results\classifications', 'results\graphs', 'results\reports')) {
        $full = Join-Path $root $d
        if (-not (Test-Path $full)) { if (-not $DryRun) { New-Item -ItemType Directory -Path $full -Force | Out-Null } }
        Add-Check "dir $d" ((Test-Path $full) -or $DryRun)
    }
}

# ---- 8. branch / commit ----------------------------------------------------
$commit = 'unknown'
if (Test-Path (Join-Path $root '.git')) {
    $commit = (& git -C $root rev-parse --short HEAD 2>$null)
    $branch = (& git -C $root rev-parse --abbrev-ref HEAD 2>$null)
    Write-Host "Branch: $branch   Commit: $commit" -ForegroundColor DarkGray
}

# ---- report ----------------------------------------------------------------
$checks | ForEach-Object { Write-Host $_ }
if ($problems.Count -gt 0) {
    Write-Host ""
    Write-Host "$($problems.Count) prerequisite problem(s):" -ForegroundColor Red
    $problems | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "Fix config.json or install the missing component. Nothing was launched." -ForegroundColor Red
    exit 2
}

Write-Host "All prerequisites satisfied." -ForegroundColor Green
if ($DryRun) { Write-Host "DryRun: no analysis launched." -ForegroundColor Yellow; exit 0 }

# ---- launch ----------------------------------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$sessionLog = Join-Path $root "logs\sessions\session_$stamp.log"
$argsList = @((Join-Path $root 'tools\analysis\controller.py'), 'run')
if ($RunOnce)   { $argsList += '--once' }
if ($MaxHours -gt 0) { $argsList += @('--max-hours', $MaxHours) }
if ($Resume)    { Write-Host "Resume: continuing from existing checkpoints." -ForegroundColor Cyan }

Write-Host "Launching: $py $($argsList -join ' ')"
& $py @argsList 2>&1 | Tee-Object -FilePath $sessionLog
$code = $LASTEXITCODE
Write-Host "Session finished with exit code $code. Log: $sessionLog"
exit $code
