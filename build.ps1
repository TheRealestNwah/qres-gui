# Builds dist\QResGUI\ (QResGUI.exe + QResLauncher.exe).
# Steam launch options and shortcuts point at QResLauncher.exe by absolute
# path, so pick a permanent home for the folder before hooking games up.
#
# -Python picks the interpreter (default: the project's .venv; CI passes "python").
param([string]$Python)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root ".venv\Scripts\python.exe" }

& $Python (Join-Path $root "tools\make_icon.py") (Join-Path $root "build\icon.ico")
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $Python -m PyInstaller --noconfirm --clean --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build\pyinstaller") (Join-Path $root "QResGUI.spec")
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Copy-Item (Join-Path $root "build\icon.png") (Join-Path $root "dist\QResGUI\icon.png")  # for notifications

# License texts travel with the program (Settings › About opens this folder).
$licenses = Join-Path $root "dist\QResGUI\licenses"
New-Item -ItemType Directory -Force $licenses | Out-Null
Copy-Item (Join-Path $root "licenses\*") $licenses
Copy-Item (Join-Path $root "THIRD_PARTY_NOTICES.md"), (Join-Path $root "LICENSE") $licenses
Write-Host "Built $(Join-Path $root 'dist\QResGUI')"
