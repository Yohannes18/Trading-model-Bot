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

REM Install requirements
if exist requirements.txt (
    echo Installing/checking requirements...
    pip install -r requirements.txt --quiet
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
