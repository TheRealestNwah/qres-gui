# Builds the release zip: release\QResGUI-<version>-win64.zip, containing the
# app plus install.cmd / install.ps1 / uninstall.ps1 so it can be installed
# without Python.
param([switch]$SkipBuild)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not $SkipBuild) {
    & (Join-Path $root "build.ps1")
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
$version = (Select-String -Path (Join-Path $root "qres_gui\__init__.py") -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$name = "QResGUI-$version-win64"
$out = Join-Path $root "release"
$stage = Join-Path $out $name
$zip = Join-Path $out "$name.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
robocopy (Join-Path $root "dist\QResGUI") $stage /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the build failed (robocopy exit code $LASTEXITCODE)." }
foreach ($file in "install.ps1", "installer\install.cmd", "installer\uninstall.ps1", "README.md", "LICENSE") {
    Copy-Item (Join-Path $root $file) $stage
}
Set-Content (Join-Path $stage "VERSION") $version -NoNewline

if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $stage -DestinationPath $zip
Write-Host "Packaged $zip ($([int]((Get-Item $zip).Length / 1MB)) MB)"
exit 0
