@echo off
REM JeaFX Backtest Runner

echo ═══════════════════════════════════════════════
echo   J e a F X   B a c k t e s t   M o d e
REM Move to script directory (project root)
cd /d %~dp0

REM Activate virtual environment
call .venv\Scripts\activate


echo Running backtest for D1...
python -m jeafx.main --backtest --pair XAUUSD --tf D1 --no-telegram

echo Running backtest for H4...
python -m jeafx.main --backtest --pair XAUUSD --tf H4 --no-telegram

echo Running backtest for H1...
python -m jeafx.main --backtest --pair XAUUSD --tf H1 --no-telegram

echo Running backtest for M30...
python -m jeafx.main --backtest --pair XAUUSD --tf M30 --no-telegram

echo All backtests complete.
pause
