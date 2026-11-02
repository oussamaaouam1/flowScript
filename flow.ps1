# Windows wrapper around google-flow's flow.py.
#   .\flow.ps1 status
#   .\flow.ps1 image -p "PROMPT" --count 3 --download 2k --out C:\path --name 01
# It sets UTF-8 mode and the PinchTab config path, and starts the PinchTab server when it is not running
# (flow.py cannot launch the npm `pinchtab` shim on Windows by itself).
param([switch]$EnsureServerOnly)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path $py)) { $py = (Get-Command python.exe | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1).Source }
$flow = Join-Path $Root 'vendor\google-flow\scripts\flow.py'
if (-not (Test-Path $flow)) { Write-Error 'google-flow is missing: run .\setup.ps1 first'; exit 1 }

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PINCHTAB_CONFIG = (pinchtab config path).Trim()

function Test-PinchTab {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:9867/health' | Out-Null; return $true } catch {
        # 401 still means the server is up
        if ($_.Exception.Response) { return $true } ; return $false
    }
}
function Find-PinchTabExe {
    # npm installs a node shim (pinchtab.ps1 / .cmd); the real binary sits in the package's .managed-bin folder.
    $root = (npm root -g 2>$null)
    if ($root) {
        $exe = Get-ChildItem (Join-Path $root.Trim() 'pinchtab\.managed-bin') -Recurse -Filter 'pinchtab-windows-*.exe' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($exe) { return $exe.FullName }
    }
    $cmd = Get-Command pinchtab.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}
if (-not (Test-PinchTab)) {
    $exe = Find-PinchTabExe
    if (-not $exe) { Write-Error 'PinchTab not found: run .\setup.ps1'; exit 1 }
    Start-Process -WindowStyle Hidden -FilePath $exe -ArgumentList 'server' | Out-Null
    for ($i = 0; $i -lt 40 -and -not (Test-PinchTab); $i++) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-PinchTab)) { Write-Error 'PinchTab server did not start (try: pinchtab server)'; exit 1 }
}
if ($EnsureServerOnly) { Write-Host 'PinchTab server: running'; exit 0 }

& $py -X utf8 $flow @args
exit $LASTEXITCODE
