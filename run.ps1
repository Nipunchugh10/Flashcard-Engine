param (
    [string]$Command = "",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating virtual environment in .venv..." -ForegroundColor Cyan
    python -m venv .venv
    Write-Host "==> Upgrading pip..." -ForegroundColor Cyan
    & $VenvPython -m pip install --quiet --upgrade pip
    Write-Host "==> Installing dependencies..." -ForegroundColor Cyan
    & $VenvPython -m pip install --quiet -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Write-Host "==> No .env found; copying .env.example -> .env" -ForegroundColor Yellow
    Copy-Item .env.example .env
    $Secret = cmd.exe /c python -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content .env) -replace "SECRET_KEY=", "SECRET_KEY=$Secret" | Set-Content .env
    Write-Host "    Generated random SECRET_KEY in .env" -ForegroundColor Green
    Write-Host "    Remember to add your GEMINI_API_KEY to .env for AI generation." -ForegroundColor Yellow
}

if ($Command -eq "test") {
    Write-Host "==> Running smoke tests..." -ForegroundColor Cyan
    & $VenvPython smoke_test.py
    exit $LASTEXITCODE
}

if ($Command -eq "security") {
    Write-Host "==> Running security tests..." -ForegroundColor Cyan
    & $VenvPython security_test.py
    exit $LASTEXITCODE
}

Write-Host "==> Recall starting on http://localhost:$Port (Ctrl-C to stop)" -ForegroundColor Green
& $VenvPython -m uvicorn app.main:app --reload --host 0.0.0.0 --port $Port
