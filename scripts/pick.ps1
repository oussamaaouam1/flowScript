# Choose the best takes of one prompt.
#
#   .\scripts\pick.ps1 -Out DIR -N 3 -Sheet          # build DIR\_sheets\03.jpg: the takes side by side, labelled 1 2 3
#   .\scripts\pick.ps1 -Out DIR -N 3 -Keep 1,3       # 03_1 -> 03_a, 03_3 -> 03_b, the rest -> DIR\_rejected\
#
# The sheet is small (about 1800 px wide), so an agent can compare the takes in one cheap image read.
param(
    [Parameter(Mandatory)][string]$Out,
    [Parameter(Mandatory)][int]$N,
    [switch]$Sheet,
    [int[]]$Keep
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$nn = '{0:D2}' -f $N
$takes = Get-ChildItem -LiteralPath $Out -File | Where-Object { $_.BaseName -match "^${nn}_(\d+)$" } |
    Sort-Object { [int]($_.BaseName -replace "^${nn}_", '') }
if (-not $takes) { Write-Error "no takes named ${nn}_1, ${nn}_2 ... in $Out"; exit 1 }

if ($Sheet) {
    $w = 600; $h = 338; $pad = 8; $label = 40
    $bmp = New-Object System.Drawing.Bitmap ($takes.Count * ($w + $pad) + $pad), ($h + 2 * $pad + $label)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::Black)
    $g.InterpolationMode = 'HighQualityBicubic'
    $font = New-Object System.Drawing.Font 'Arial', 22, ([System.Drawing.FontStyle]::Bold)
    $i = 0
    foreach ($t in $takes) {
        $img = [System.Drawing.Image]::FromFile($t.FullName)
        $x = $pad + $i * ($w + $pad)
        $g.DrawImage($img, $x, $pad + $label, $w, $h)
        $g.DrawString(($t.BaseName -replace "^${nn}_", ''), $font, [System.Drawing.Brushes]::White, $x, 6)
        $img.Dispose(); $i++
    }
    $dir = Join-Path $Out '_sheets'; New-Item -ItemType Directory -Force $dir | Out-Null
    $path = Join-Path $dir "$nn.jpg"
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Jpeg); $g.Dispose(); $bmp.Dispose()
    Write-Output $path
}

if ($Keep) {
    $letters = 'abcdefghij'
    $rej = Join-Path $Out '_rejected'; New-Item -ItemType Directory -Force $rej | Out-Null
    $k = 0
    foreach ($num in $Keep) {
        $t = $takes | Where-Object { $_.BaseName -eq "${nn}_$num" }
        if (-not $t) { Write-Error "take ${nn}_$num not found"; exit 1 }
        Rename-Item -LiteralPath $t.FullName -NewName ("{0}_{1}{2}" -f $nn, $letters[$k], $t.Extension); $k++
    }
    foreach ($t in $takes) {
        $num = [int]($t.BaseName -replace "^${nn}_", '')
        if ($Keep -notcontains $num -and (Test-Path -LiteralPath $t.FullName)) { Move-Item -LiteralPath $t.FullName -Destination $rej -Force }
    }
    Get-ChildItem -LiteralPath $Out -File | Where-Object { $_.BaseName -like "${nn}_*" } | ForEach-Object { $_.Name }
}
