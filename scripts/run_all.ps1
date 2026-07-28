$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "bootstrap.ps1")
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

& $Python dataset\scripts\generate_dataset.py
& $Python dataset\scripts\compile_dataset.py
& $Python dataset\scripts\validate_dataset.py
& $Python dataset\scripts\run_experiments.py
& $Python dataset\scripts\run_fuzz_budget_sweep.py
& $Python dataset\scripts\run_scalability.py
& $Python dataset\scripts\replay_counterexamples.py

Write-Output "Pipeline complete. See dataset\results\summary\run_manifest.json."
