# Builds vendor\ (embeddable Python + the wheels the host imports) and compiles the installer.
#
# Run from the repository root:  .\installer\build.ps1
# Needs Inno Setup 6.3+ (ISCC.exe) and this machine's project venv for pip.
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.9",
    [string]$Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    [string]$BuildPython = "J:\40k-assistant\venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root "vendor"
$python = Join-Path $vendor "python"

Write-Output "building the vendor tree for Python $PythonVersion"
if (Test-Path $vendor) { Remove-Item -Recurse -Force $vendor }
New-Item -ItemType Directory -Force $python | Out-Null

$zipUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$zip = Join-Path $env:TEMP "python-embed-$PythonVersion.zip"
if (-not (Test-Path $zip)) { Invoke-WebRequest -Uri $zipUrl -OutFile $zip }
Expand-Archive -Path $zip -DestinationPath $python -Force

# The embeddable distribution has a fixed sys.path: exactly the entries of its ._pth file,
# resolved against the interpreter's own folder. The current directory is NOT added, so without
# "..\.." the shortcut `pythonw.exe -m standalone` cannot find the package at the install root
# (measured 2026-10-13: "No module named standalone"). site-packages needs saying too.
$pth = Get-ChildItem -Path $python -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "the embeddable archive has no ._pth file" }
Add-Content -Path $pth.FullName -Value "Lib\site-packages" -Encoding utf8
Add-Content -Path $pth.FullName -Value "..\.." -Encoding utf8   # the install root

# pystray (the tray icon) needs Pillow and six; the connector needs numpy and zstandard.
& $BuildPython -m pip install --no-deps --only-binary :all: `
    --target (Join-Path $python "Lib\site-packages") numpy zstandard pillow pystray six
if ($LASTEXITCODE -ne 0) { throw "installing the wheels failed" }

# The packaged interpreter must import what the host imports; judged by the exit code, never by text.
& (Join-Path $python "python.exe") -c "import numpy, zstandard, PIL, pystray; print('ok')"
if ($LASTEXITCODE -ne 0) { throw "the packaged interpreter cannot import the dependencies" }

# Nothing of Hello Games' and nothing LGPL may be packaged: mapping.json is downloaded at runtime, and
# the item database and icons are built from the user's own installation.
foreach ($forbidden in @("mapping.json", "gamedata", ".data")) {
    $hits = Get-ChildItem -Path $root -Recurse -Force -Filter $forbidden -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "*\.git\*" -and $_.FullName -notlike "*\tests\*" }
    if ($hits) { throw "the tree contains $forbidden; it must not be packaged" }
}

$manifest = Get-Content (Join-Path $root "strategicum-plugin.json") -Raw | ConvertFrom-Json
$version = $manifest.version
Write-Output "compiling the installer for $version"
& $Iscc "/DMyAppVersion=$version" (Join-Path $PSScriptRoot "nms-companion.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Write-Output "built installer\Output\nms-companion-$version-setup.exe"
