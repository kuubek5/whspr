# build.ps1 -- freeze whspr and package the installer. Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "==> PyInstaller build" -ForegroundColor Cyan
& "$root\.venv\Scripts\pyinstaller.exe" packaging\whspr.spec --noconfirm `
    --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Inno Setup can be installed system-wide OR per-user (its installer offers
# both, and the per-user option needs no admin rights). Only checking Program
# Files meant a perfectly good per-user install was ignored and the packaging
# step silently skipped, leaving dist\whspr but no setup.exe.
$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $iscc = $isccCandidates[0]  # for the message below
    Write-Warning "Inno Setup not found at $iscc -- install it, then run:"
    Write-Warning "  & `"$iscc`" packaging\whspr.iss"
    Write-Host "Frozen app is ready in dist\whspr" -ForegroundColor Green
    exit 0
}

Write-Host "==> Inno Setup packaging" -ForegroundColor Cyan
& $iscc packaging\whspr.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

# Report what was actually produced rather than a hardcoded name: the installer
# filename carries the version now, so a stale literal here would drift every
# time the version is bumped.
$built = Get-ChildItem "$root\packaging\Output\*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "Installer: $($built.FullName) ($([math]::Round($built.Length/1MB,1)) MB)" -ForegroundColor Green
