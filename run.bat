@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem -- Check UV --
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERR] 'uv' not found. Install with:
    echo        pip install uv
    echo    or  powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    pause
    exit /b 1
)

rem -- Create venv if missing --
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment with UV...
    uv venv --python 3.12 .venv
    if %errorlevel% neq 0 (
        echo [ERR] Failed to create venv
        pause
        exit /b 1
    )
    echo [*] Installing dependencies...
    uv pip install -r requirements.txt --python .venv\Scripts\python.exe
    if %errorlevel% neq 0 (
        echo [WARN] Dependency install had issues -- continuing anyway
    )
    echo [+] Environment ready.
    echo.
)

rem -- Launch --
set VENV_PYTHON=.venv\Scripts\python.exe
"%VENV_PYTHON%" -m viralxscraper.cli

if %errorlevel% neq 0 (
    echo.
    echo [!] Scraper exited with code %errorlevel%
    pause
)
