@echo off
rem Double-click installer for the release zip; runs install.ps1 next to it.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
