# flowScript setup for Windows. Run once, from PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
# What it does (nothing else):
#   1. Installs Python 3.12 (winget, per-user) and PinchTab (npm -g) if they are missing.
#   2. Downloads the google-flow skill (YusufLisawi/bb-plugins) at a pinned commit into .\vendor\google-flow.
#   3. Creates the PinchTab config if needed and, after a backup (config.json.bak-flowscript), turns on the two
#      PinchTab permissions google-flow needs (allowEvaluate, allowCookies) and allows the Google/Flow domains.
#      This lets the separate PinchTab automation browser run scripts on, and keep cookies for, those domains only.
#   4. Starts the PinchTab server (localhost only, token-protected).
param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$UpstreamRepo = 'https://github.com/YusufLisawi/bb-plugins.git'
$UpstreamCommit = 'fcf44f0cfad8348122cd653e737889e59c6e2edc'

function Find-Python {
    $p = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path $p) { return $p }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
    if ($c) { return $c.Source }
    return $null
}

# 1. dependencies
if (-not $SkipInstall) {
    if (-not (Find-Python)) {
        Write-Host 'Installing Python 3.12 (winget, user scope)...'
        winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
    }
    if (-not (Get-Command pinchtab -ErrorAction SilentlyContinue)) {
        Write-Host 'Installing PinchTab (npm -g)...'
        npm install -g pinchtab@0.15.2
    }
}
$py = Find-Python
if (-not $py) { throw 'Python 3.9+ not found' }
Write-Host "python:   $py"
Write-Host "pinchtab: $((pinchtab --version) -join ' ')"

# 2. google-flow skill at a pinned commit
$vendor = Join-Path $Root 'vendor'
$gf = Join-Path $vendor 'google-flow'
if (-not (Test-Path (Join-Path $gf 'scripts\flow.py'))) {
    $tmp = Join-Path $env:TEMP ('bb-plugins-' + [guid]::NewGuid().ToString('N'))
    git clone --quiet --filter=blob:none --no-checkout $UpstreamRepo $tmp
    git -C $tmp checkout --quiet $UpstreamCommit -- skills/google-flow
    New-Item -ItemType Directory -Force $vendor | Out-Null
    Copy-Item -Recurse (Join-Path $tmp 'skills\google-flow') $gf
    Remove-Item -Recurse -Force $tmp
}
Write-Host "google-flow: $gf (commit $($UpstreamCommit.Substring(0,7)))"

# 3. PinchTab config
$ptConf = (pinchtab config path).Trim()
if (-not (Test-Path $ptConf)) { pinchtab config init | Out-Null }
$bak = "$ptConf.bak-flowscript"
if (-not (Test-Path $bak)) { Copy-Item $ptConf $bak }
& $py -X utf8 (Join-Path $Root 'scripts\pinchtab_conf.py') $ptConf
if ($LASTEXITCODE -ne 0) { throw 'could not update the PinchTab config' }

# 4. server
& (Join-Path $Root 'flow.ps1') -EnsureServerOnly
Write-Host ''
Write-Host 'Done. Next: sign in once ->  .\flow.ps1 login   (or  .\flow.ps1 setup --cookies <export.json>)'
