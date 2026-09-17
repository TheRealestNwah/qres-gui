<#
.SYNOPSIS
Writes the winget manifests for a published QRes GUI release.

.DESCRIPTION
Reads the release's setup.exe from GitHub (its download URL and the SHA-256
GitHub lists for it - nothing is downloaded) and writes the three manifest files
winget-pkgs wants to winget\manifests\t\TheRealestNwah\QResGUI\<version>\.
Check them with `winget validate`, try them with `winget install --manifest`,
then submit that folder to https://github.com/microsoft/winget-pkgs
(docs/RELEASING.md has the steps).

.PARAMETER Version
The released version, e.g. 1.9.0. Its GitHub release must have
QResGUI-<version>-setup.exe.

.PARAMETER OutDir
Where to write the files instead (for trying the script out).

.PARAMETER Asset
Another asset of the release to point the installer entry at - only for
checking the manifest format against a release that has no setup.exe.
#>
param([Parameter(Mandatory)][string]$Version, [string]$OutDir, [string]$Asset)
$ErrorActionPreference = "Stop"

$repo = "TheRealestNwah/qres-gui"
$id = "TheRealestNwah.QResGUI"
$schema = "1.12.0"
$asset = if ($Asset) { $Asset } else { "QResGUI-$Version-setup.exe" }

$release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/tags/v$Version" -Headers @{ "User-Agent" = "qres-gui-release" }
$setup = $release.assets | Where-Object name -eq $asset
if (-not $setup) { throw "Release v$Version has no $asset." }
if ($setup.digest -notmatch '^sha256:([0-9a-f]{64})$') { throw "GitHub lists no SHA-256 for $asset." }
$sha = $Matches[1].ToUpper()
$date = ([datetime]$release.published_at).ToString("yyyy-MM-dd")

$out = if ($OutDir) { $OutDir } else { Join-Path $PSScriptRoot "..\winget\manifests\t\TheRealestNwah\QResGUI\$Version" }
New-Item -ItemType Directory -Force $out | Out-Null

$files = @{
    "$id.yaml" = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.version.$schema.schema.json

PackageIdentifier: $id
PackageVersion: $Version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: $schema
"@
    "$id.installer.yaml" = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.installer.$schema.schema.json

PackageIdentifier: $id
PackageVersion: $Version
MinimumOSVersion: 10.0.0.0
InstallerType: inno
Scope: user
InstallModes:
- interactive
- silent
- silentWithProgress
UpgradeBehavior: install
ExpectedReturnCodes:
- InstallerReturnCode: 2
  ReturnResponse: packageInUse
ReleaseDate: $date
AppsAndFeaturesEntries:
- DisplayName: QRes GUI
  Publisher: TheRealestNwah
  ProductCode: QResGUI
InstallationMetadata:
  DefaultInstallLocation: '%LOCALAPPDATA%\Programs\QResGUI'
Installers:
- Architecture: x64
  InstallerUrl: $($setup.browser_download_url)
  InstallerSha256: $sha
ManifestType: installer
ManifestVersion: $schema
"@
    "$id.locale.en-US.yaml" = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.defaultLocale.$schema.schema.json

PackageIdentifier: $id
PackageVersion: $Version
PackageLocale: en-US
Publisher: TheRealestNwah
PublisherUrl: https://github.com/TheRealestNwah
PublisherSupportUrl: https://github.com/$repo/issues
Author: TheRealestNwah
PackageName: QRes GUI
PackageUrl: https://github.com/$repo
License: MIT
LicenseUrl: https://github.com/$repo/blob/main/LICENSE
ShortDescription: Switches Windows to a game's resolution while it runs, and back when it closes.
Description: |-
  QRes GUI switches the desktop to a chosen resolution, refresh rate, HDR state and scaling mode while a
  particular game runs, and back when it exits. It hooks into Steam launch options, Playnite's scripts
  and shortcuts, and can switch for games started from any other launcher while it runs in the tray.
  Resolution changes go through QRes.exe when it's available, and the Windows display API otherwise.
Moniker: qres-gui
Tags:
- display
- gaming
- hdr
- resolution
- steam
- ultrawide
ReleaseNotesUrl: https://github.com/$repo/releases/tag/v$Version
Documentations:
- DocumentLabel: Troubleshooting
  DocumentUrl: https://github.com/$repo/blob/main/docs/TROUBLESHOOTING.md
ManifestType: defaultLocale
ManifestVersion: $schema
"@
}
foreach ($name in $files.Keys) {
    # winget-pkgs wants UTF-8 without a BOM.
    [IO.File]::WriteAllText((Join-Path $out $name), $files[$name].Replace("`r`n", "`n") + "`n", [Text.UTF8Encoding]::new($false))
}
Write-Host "Wrote the manifests for $id $Version to $((Resolve-Path $out).Path)"
