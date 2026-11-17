# Builds the Windows installer: freezes the app with PyInstaller, checks the frozen copy works, then runs Inno Setup.
# Usage, from anywhere:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Output: build\installer\handctl-setup-<version>.exe
# Needs: the .venv with the project installed (pip install -e ".[dev]" pyinstaller), both model files, Inno Setup 6.

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

function Fail($message) { Write-Host "BUILD FAILED: $message" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $python)) { Fail "no .venv found at $python. See README > Install." }
foreach ($model in "gesture_recognizer.task", "face_landmarker.task") {
    if (-not (Test-Path (Join-Path $root "handctl\models\$model"))) { Fail "handctl\models\$model is missing. See README > Install." }
}
$version = (Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
if (-not $version) { Fail "couldn't read the version from pyproject.toml" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Fail "Inno Setup 6 isn't installed. Install it with: winget install JRSoftware.InnoSetup" }

Write-Host "Freezing handctl $version (takes a few minutes)..."
& $python -m PyInstaller --noconfirm --clean --windowed --log-level WARN --name handctl `
    --distpath "$root\build\dist" --workpath "$root\build\work" --specpath "$root\build" `
    --collect-all mediapipe --add-data "$root\handctl\models\*.task;handctl\models" `
    --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 `
    "$root\installer\entry.py"
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller exited with code $LASTEXITCODE" }

Write-Host "Checking the frozen app..."
# the app has no console window, so wait for it explicitly to get its exit code
$check = Start-Process -FilePath "$root\build\dist\handctl\handctl.exe" -ArgumentList "--check" -Wait -PassThru
if ($check.ExitCode -ne 0) { Fail "the frozen app failed its self-check; details in $env:TEMP\handctl-check.log" }

Write-Host "Building the installer..."
# Inno Setup can't read paths longer than 260 characters, and the frozen app's deepest files pass that when the
# project sits in a long folder. A temporary drive letter for the project folder keeps every path short.
$drive = [char[]]"ZYXWVUTSRQPONMLKJ" | ForEach-Object { "${_}:" } | Where-Object { -not (Test-Path "$_\") } | Select-Object -First 1
if (-not $drive) { Fail "no free drive letter to shorten the build paths" }
subst $drive $root
if ($LASTEXITCODE -ne 0) { Fail "couldn't map $drive to the project folder" }
try {
    & $iscc /Q "/DAppVersion=$version" "$drive\installer\handctl.iss"
    $code = $LASTEXITCODE
} finally {
    subst $drive /D | Out-Null
}
if ($code -ne 0) { Fail "Inno Setup exited with code $code" }
Write-Host "Done: $root\build\installer\handctl-setup-$version.exe" -ForegroundColor Green
