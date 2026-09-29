$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Backend virtual environment not found at $venvPython. Run: python -m venv backend\.venv ; backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt"
    exit 1
}

Write-Host "Starting backend (FastAPI) in a new window..." -ForegroundColor Blue
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$backend'; & '$venvPython' -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
)

Write-Host "Starting frontend (Vite) in a new window..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$frontend'; npm run dev"
)

Write-Host "Backend  -> http://localhost:8000" -ForegroundColor Blue
Write-Host "Frontend -> http://localhost:3000" -ForegroundColor Green
