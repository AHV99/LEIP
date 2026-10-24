<##
Ejecutar desde PowerShell:
  .\scripts\probar-docling.ps1
Para instalar en un entorno nuevo antes de ejecutar:
  .\scripts\probar-docling.ps1 -Instalar
##>
param([switch]$Instalar)

$ErrorActionPreference = 'Stop'
$repoDirectory = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $repoDirectory '.venv/Scripts/python.exe'

Push-Location -LiteralPath $repoDirectory
try {
    if (-not (Test-Path -LiteralPath $pythonExecutable)) {
        if (-not $Instalar) {
            throw 'Falta .venv. Ejecutar este script con -Instalar.'
        }
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
    }
    if ($Instalar) {
        & $pythonExecutable -m pip install -e '.[docling,test]'
        if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de dependencias.' }
    }
    & $pythonExecutable -c 'import docling; import pytest'
    if ($LASTEXITCODE -ne 0) {
        throw 'Docling aún no está instalado. Dejar terminar la descarga actual o usar -Instalar en un entorno nuevo.'
    }
    & $pythonExecutable -m pytest tests/test_docling.py --bcu --docling -q -s --junitxml=work/docling-results.xml
    if ($LASTEXITCODE -ne 0) { throw 'La comprobación real con Docling no pasó; revisar la salida y work/docling-results.xml.' }
} finally {
    Pop-Location
}
