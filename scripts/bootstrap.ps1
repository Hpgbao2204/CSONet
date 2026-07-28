$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonEnv = Join-Path $ProjectRoot ".venv"
$PipCache = Join-Path $ProjectRoot ".cache\pip"
$NpmCache = Join-Path $ProjectRoot ".cache\npm"
$FoundryCache = Join-Path $ProjectRoot ".cache\foundry"
$FoundryDir = Join-Path $ProjectRoot ".tools\foundry"
$FoundryVersion = "v1.7.1"
$FoundryArchive = "foundry_v1.7.1_win32_amd64.zip"
$FoundrySha256 = "6d41121b4bbb809845821c903619cfee75ed364f2bdc58a6787c9b0454114537"

New-Item -ItemType Directory -Force -Path $PipCache, $NpmCache, $FoundryCache, $FoundryDir | Out-Null

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

if (-not (Test-Path (Join-Path $FoundryDir "anvil.exe"))) {
    $ArchivePath = Join-Path $FoundryCache $FoundryArchive
    $DownloadUrl = "https://github.com/foundry-rs/foundry/releases/download/$FoundryVersion/$FoundryArchive"
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath
    $ActualSha256 = (Get-FileHash -Algorithm SHA256 $ArchivePath).Hash.ToLower()
    if ($ActualSha256 -ne $FoundrySha256) {
        throw "Foundry archive checksum mismatch"
    }
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $FoundryDir -Force
}

Write-Output "Local environment ready: $PythonEnv"
Write-Output "Local Foundry ready: $FoundryDir"
