# Prints release notes for one version: its CHANGELOG.md section plus the
# standard install / update text. Used by CI when a v* tag is pushed.
#   .\tools\release-notes.ps1 -Version 0.7.0
param([Parameter(Mandatory)][string]$Version)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

$lines = Get-Content (Join-Path $root "CHANGELOG.md") -Encoding utf8
$start = ($lines | Select-String -Pattern "^## $([regex]::Escape($Version))\b" | Select-Object -First 1).LineNumber
if (-not $start) { throw "CHANGELOG.md has no '## $Version' section." }
$section = @()
foreach ($line in $lines[$start..($lines.Count - 1)]) {
    if ($line -match "^## ") { break }
    $section += $line
}

# Relative links work in the repository but not on a release page.
$body = ($section -join "`n").Trim() -replace '\]\((?!https?://)([^)]+)\)', '](https://github.com/TheRealestNwah/qres-gui/blob/main/$1)'

@"
$body

## Install / update

Download ``QResGUI-$Version-win64.zip`` below, extract it, and double-click ``install.cmd``. Updating keeps your settings, Steam launch options, Playnite scripts and shortcuts. You need ``QRes.exe`` (v1.1 by Anders Kjersem, not included); QRes GUI asks where it is on first start.

Windows 10/11. The executables aren't code-signed, so SmartScreen may warn on first run. Problems? See [Troubleshooting](https://github.com/TheRealestNwah/qres-gui/blob/main/docs/TROUBLESHOOTING.md).
"@
