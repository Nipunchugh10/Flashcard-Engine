@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo ==^> Creating virtual environment in .venv...
    python -m venv .venv
    echo ==^> Installing dependencies from requirements.txt...
    "%VENV_PYTHON%" -m pip install --quiet -r requirements.txt
)

if not exist ".env" (
    echo ==^> Copying .env.example to .env...
    copy .env.example .env
)

if "%1"=="test" (
    echo ==^> Running smoke tests...
    "%VENV_PYTHON%" smoke_test.py
    exit /b %ERRORLEVEL%
)

if "%1"=="security" (
    echo ==^> Running security tests...
    "%VENV_PYTHON%" security_test.py
    exit /b %ERRORLEVEL%
)

set PORT=8000
if not "%PORT_ENV%"=="" set PORT=%PORT_ENV%

echo ==^> Recall starting on http://localhost:%PORT%   (Ctrl-C to stop)
"%VENV_PYTHON%" -m uvicorn app.main:app --reload --host 0.0.0.0 --port %PORT%
