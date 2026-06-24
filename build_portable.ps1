param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

Write-Host "Using Python:" $PythonExe

& $PythonExe -m pip install --upgrade pip | Out-Host
& $PythonExe -m pip install -r .\video_combiner\requirements.txt pyinstaller | Out-Host

if (Test-Path .\build) {
    Remove-Item .\build -Recurse -Force
}
if (Test-Path .\dist\VideoCombinerPortable.exe) {
    Remove-Item .\dist\VideoCombinerPortable.exe -Force
}

& $PythonExe -m PyInstaller --noconfirm .\VideoCombinerPortable.spec | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$dataDir = ".\dist\data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
if (-not (Test-Path "$dataDir\canvas_presets.user.json")) {
    Copy-Item ".\video_combiner\assets\canvas_presets.user.json" "$dataDir\canvas_presets.user.json" -Force
}

Write-Host ""
Write-Host "Portable EXE built:"
Write-Host "  .\dist\VideoCombinerPortable.exe"
Write-Host ""
Write-Host "Runtime presets JSON (created/updated next to EXE):"
Write-Host "  .\dist\data\canvas_presets.user.json"
