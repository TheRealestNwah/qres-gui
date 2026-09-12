<#
.SYNOPSIS
Uninstalls QRes GUI (install.ps1 copies this script into the install folder).

.DESCRIPTION
Takes QRes out of Steam launch options and Playnite's scripts and deletes the
game shortcuts first, so nothing is left pointing at a launcher that no longer
exists. Then removes
the Start menu folder, the Settings > Apps entry, the notification
registration and the program folder.
Settings in %APPDATA%\QResGUI are kept unless you say otherwise.

.PARAMETER Quiet
No prompts: keeps settings, and gives up if Steam has to be closed first.

.PARAMETER RemoveSettings
Also delete %APPDATA%\QResGUI.
#>
param([switch]$Quiet, [switch]$RemoveSettings)
$ErrorActionPreference = "Stop"

$dest = $PSScriptRoot
$launcher = Join-Path $dest "QResLauncher.exe"
$menu = Join-Path ([Environment]::GetFolderPath("Programs")) "QRes GUI"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\QResGUI"
$settings = Join-Path $env:APPDATA "QResGUI"

function Finish([int]$code) {
    if (-not $Quiet) { Read-Host "Press Enter to close" | Out-Null }
    exit $code
}

try {
    $running = Get-Process QResGUI, QResLauncher -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($dest, [StringComparison]::OrdinalIgnoreCase) }
    if ($running) {
        Write-Host "QRes GUI, or a game started through it, is running. Close it and try again."
        Finish 1
    }

    if (Test-Path $launcher) {
        $report = Join-Path $env:TEMP "qresgui-remove-hooks.json"
        while ($true) {
            $proc = Start-Process $launcher -ArgumentList "remove-hooks", "`"$report`"" -Wait -PassThru
            if ($proc.ExitCode -eq 0) { break }
            if ($proc.ExitCode -eq 4) {
                # 4: Playnite is open, and it saves its settings (scripts included) when it exits.
                if ($Quiet) {
                    Write-Host "Playnite is running. Close it and uninstall again."
                    Finish 1
                }
                $answer = Read-Host "Close Playnite so QRes can be taken out of its scripts, then press Enter (or type n to cancel)"
                if ($answer -match "^n") {
                    Write-Host "Uninstall cancelled. Nothing was removed."
                    Finish 1
                }
                continue
            }
            if ($proc.ExitCode -ne 3) {
                throw "Removing hooks failed (exit code $($proc.ExitCode)). See $settings\launcher.log"
            }
            # 3: Steam is open, and it overwrites its launch options when it exits.
            if ($Quiet) {
                Write-Host "Steam is running. Close it and uninstall again."
                Finish 1
            }
            $answer = Read-Host "Steam has to be closed to remove QRes from its launch options. Close Steam now? [Y/n]"
            if ($answer -match "^n") {
                Write-Host "Uninstall cancelled. Nothing was removed."
                Finish 1
            }
            $steamExe = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue).SteamExe
            if ($steamExe) { Start-Process $steamExe -ArgumentList "-shutdown" }
            Write-Host "Waiting for Steam to exit..."
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Process steam -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
            }
        }
        $summary = Get-Content $report -Raw | ConvertFrom-Json
        Remove-Item $report -ErrorAction SilentlyContinue
        Write-Host "Removed QRes from $(@($summary.steam).Count) Steam game(s) and deleted $(@($summary.shortcuts).Count) game shortcut(s)."
        if ($summary.playnite) { Write-Host "Removed QRes from Playnite's scripts." }
    }

    Remove-Item $menu -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "HKCU:\Software\Classes\AppUserModelId\QResGUI" -Recurse -Force -ErrorAction SilentlyContinue

    $deleteSettings = $RemoveSettings
    if (-not $deleteSettings -and -not $Quiet -and (Test-Path $settings)) {
        $deleteSettings = (Read-Host "Also delete your QRes GUI settings in $settings? [y/N]") -match "^y"
    }
    if ($deleteSettings) { Remove-Item $settings -Recurse -Force -ErrorAction SilentlyContinue }

    # PowerShell has already read this whole script, so deleting its folder is fine.
    Set-Location $env:TEMP
    Remove-Item $dest -Recurse -Force
    Write-Host "QRes GUI has been uninstalled."
    Finish 0
}
catch {
    Write-Host "Uninstall failed: $_" -ForegroundColor Red
    Finish 1
}
