$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No se encontró el entorno virtual: $python. Créalo e instala requirements-build.txt primero."
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean Free2Play.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller terminó con código $LASTEXITCODE."
    }
    Write-Host "Aplicación compilada en: $(Join-Path $projectRoot 'dist\Free2Play')"
} finally {
    Pop-Location
}
