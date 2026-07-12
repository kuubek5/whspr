# build.ps1 — freeze whspr and package the installer. Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "==> PyInstaller build" -ForegroundColor Cyan
& "$root\.venv\Scripts\pyinstaller.exe" packaging\whspr.spec --noconfirm `
    --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    Write-Warning "Inno Setup not found at $iscc — install it, then run:"
    Write-Warning "  & `"$iscc`" packaging\whspr.iss"
    Write-Host "Frozen app is ready in dist\whspr" -ForegroundColor Green
    exit 0
}

Write-Host "==> Inno Setup packaging" -ForegroundColor Cyan
& $iscc packaging\whspr.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "Installer: packaging\Output\whspr-setup.exe" -ForegroundColor Green
