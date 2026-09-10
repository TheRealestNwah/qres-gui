<#
.SYNOPSIS
Builds QRes GUI and installs it for the current user.

.DESCRIPTION
Installs to %LOCALAPPDATA%\Programs\QResGUI, adds a Start menu shortcut and an
entry in Settings > Apps (which runs uninstall.ps1). Re-run it to update: the
install folder never changes, so Steam launch options and game shortcuts keep
working across updates.

.PARAMETER SkipBuild
Install the existing dist\QResGUI build instead of rebuilding first.
#>
param([switch]$SkipBuild)
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$dist = Join-Path $root "dist\QResGUI"
$dest = Join-Path $env:LOCALAPPDATA "Programs\QResGUI"
$exe = Join-Path $dest "QResGUI.exe"
$menu = Join-Path ([Environment]::GetFolderPath("Programs")) "QRes GUI"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\QResGUI"

if (-not $SkipBuild) {
    & (Join-Path $root "build.ps1")
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
if (-not (Test-Path (Join-Path $dist "QResLauncher.exe"))) {
    throw "No build in $dist - run without -SkipBuild."
}

# Files in use can't be replaced, and a running launcher means a game is switched.
$running = Get-Process QResGUI, QResLauncher -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($dest, [StringComparison]::OrdinalIgnoreCase) }
if ($running) {
    throw "QRes GUI, or a game started through it, is running. Close it and run the installer again."
}

robocopy $dist $dest /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying files failed (robocopy exit code $LASTEXITCODE)." }
Copy-Item (Join-Path $root "installer\uninstall.ps1") $dest

New-Item -ItemType Directory -Force $menu | Out-Null
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $menu "QRes GUI.lnk"))
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $dest
$shortcut.IconLocation = "$exe,0"
$shortcut.Description = "Per-game resolution switching through QRes"
$shortcut.Save()

$version = (Select-String -Path (Join-Path $root "qres_gui\__init__.py") -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$sizeKb = [int]((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
$uninstall = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`""
New-Item -Path $uninstallKey -Force | Out-Null
$strings = @{
    DisplayName          = "QRes GUI"
    DisplayVersion       = $version
    DisplayIcon          = "$exe,0"
    InstallLocation      = $dest
    UninstallString      = $uninstall
    QuietUninstallString = "$uninstall -Quiet"
}
foreach ($name in $strings.Keys) {
    New-ItemProperty -Path $uninstallKey -Name $name -Value $strings[$name] -PropertyType String -Force | Out-Null
}
foreach ($pair in @(@("NoModify", 1), @("NoRepair", 1), @("EstimatedSize", $sizeKb))) {
    New-ItemProperty -Path $uninstallKey -Name $pair[0] -Value $pair[1] -PropertyType DWord -Force | Out-Null
}

Write-Host "Installed QRes GUI $version to $dest"
exit 0  # robocopy leaves a non-zero $LASTEXITCODE even on success
