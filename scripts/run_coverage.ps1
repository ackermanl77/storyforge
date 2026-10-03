param(
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "No se encontró .venv\Scripts\python.exe. Crea o activa el entorno antes de correr cobertura."
}

Set-Location $RepoRoot
& $Python -m pytest --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml @PytestArgs
