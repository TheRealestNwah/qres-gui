# Builds dist\QResGUI\ (QResGUI.exe + QResLauncher.exe).
# Steam launch options and shortcuts point at QResLauncher.exe by absolute
# path, so pick a permanent home for the folder before hooking games up.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

& $py (Join-Path $root "tools\make_icon.py") (Join-Path $root "build\icon.ico")
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $py -m PyInstaller --noconfirm --clean --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build\pyinstaller") (Join-Path $root "QResGUI.spec")
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Write-Host "Built $(Join-Path $root 'dist\QResGUI')"
