$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonEnv = Join-Path $ProjectRoot ".venv"
$PipCache = Join-Path $ProjectRoot ".cache\pip"
$NpmCache = Join-Path $ProjectRoot ".cache\npm"

New-Item -ItemType Directory -Force -Path $PipCache, $NpmCache | Out-Null

if (-not (Test-Path $PythonEnv)) {
    python -m venv $PythonEnv
}

& (Join-Path $PythonEnv "Scripts\python.exe") -m pip install `
    --cache-dir $PipCache --requirement (Join-Path $ProjectRoot "requirements.txt")

Push-Location $ProjectRoot
try {
    & npm.cmd install --cache $NpmCache
}
finally {
    Pop-Location
}

Write-Output "Local environment ready: $PythonEnv"

