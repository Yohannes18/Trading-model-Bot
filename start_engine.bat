@echo off
title Quantara Trading Engine v5
cls

echo ═══════════════════════════════════════════════
echo   Q u a n t a r a   A d a p t i v e   E n g i n e
echo   v5.0  —  SMC + Confidence + Stress + MT5
echo ═══════════════════════════════════════════════
echo.

REM Move to script directory (project root)
cd /d %~dp0

REM Create virtual environment if it doesn't exist
if not exist .venv (
    echo Creating virtual environment...
    py -m venv .venv
    echo.
)

REM Activate virtual environment
call .venv\Scripts\activate
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Install requirements
if exist requirements.txt (
    echo Installing/checking requirements from requirements.txt...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency installation failed. Fix the issue and run again.
        pause
        exit /b 1
    )
    echo.
)

:start
echo Starting Quantara engine...
python -m quantara.main --all

echo.
echo ═══════════════════════════════════════════════
echo   Engine stopped. Restarting in 10 seconds...
echo   Press Ctrl+C to exit permanently.
echo ═══════════════════════════════════════════════
timeout /t 10
goto start
