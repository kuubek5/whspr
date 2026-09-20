# publish-release.ps1 -- cut a GitHub Release for the current version and upload
# the installer the in-app updater downloads. Run AFTER packaging\build.ps1:
#   powershell -ExecutionPolicy Bypass -File packaging\publish-release.ps1
#
# The version comes from flow.APP_VERSION (the single source of truth). The
# release lives in the PUBLIC releases-only repo the updater polls (GITHUB_REPO
# in flow.py) -- source stays in the private repo, only the built installer and
# release notes are public. Needs the GitHub CLI (gh) authenticated.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# --- version + repo, read from flow.py so nothing is hardcoded here ---
$verMatch = Select-String -Path "$root\flow.py" -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $verMatch) { throw "APP_VERSION not found in flow.py" }
$Version = $verMatch.Matches[0].Groups[1].Value
$repoMatch = Select-String -Path "$root\flow.py" -Pattern '^GITHUB_REPO\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $repoMatch) { throw "GITHUB_REPO not found in flow.py" }
$Repo = $repoMatch.Matches[0].Groups[1].Value
$Tag = "v$Version"

# --- the installer build.ps1 produced (filename carries the version) ---
$Installer = "$root\packaging\Output\kuubwave-setup-$Version.exe"
if (-not (Test-Path $Installer)) {
    throw "Installer not found: $Installer -- run packaging\build.ps1 first"
}

# --- gh must be present and authenticated ---
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) not found -- install it and run 'gh auth login'"
}
# gh reports state on stderr and through exit codes (e.g. "release view" exits
# non-zero when the release does not exist yet -- the normal case here). Under
# ErrorActionPreference=Stop, Windows PowerShell 5.1 turns those stderr writes
# into terminating errors, so drop to Continue around the native gh calls and
# check $LASTEXITCODE ourselves. (Cmdlet errors above still stop the script.)
$ErrorActionPreference = "Continue"

& gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "gh is not authenticated -- run 'gh auth login'" }

Write-Host "==> Publishing $Tag to $Repo" -ForegroundColor Cyan
Write-Host "    asset: $Installer" -ForegroundColor DarkGray

# Refuse to clobber an existing release: a re-cut of the same version is almost
# always a mistake (the updater keys on the tag). Bump APP_VERSION instead.
& gh release view $Tag --repo $Repo 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    throw "Release $Tag already exists in $Repo -- bump APP_VERSION and rebuild"
}

$notes = "KuubWave $Version`n`nAutomatic in-app update: existing installs pick this up on next launch."
& gh release create $Tag $Installer --repo $Repo --title "KuubWave $Version" --notes $notes
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }

Write-Host "Released $Tag -- installs on $($Version) and newer will offer it automatically." -ForegroundColor Green
