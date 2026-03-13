@echo off
REM Quantara Backtest Runner

echo ═══════════════════════════════════════════════
echo   Q u a n t a r a   B a c k t e s t   M o d e
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


echo Running backtest for D1...
python -m quantara.main --backtest --pair XAUUSD --tf D1 --no-telegram

echo Running backtest for H4...
python -m quantara.main --backtest --pair XAUUSD --tf H4 --no-telegram

echo Running backtest for H1...
python -m quantara.main --backtest --pair XAUUSD --tf H1 --no-telegram

echo Running backtest for M30...
python -m quantara.main --backtest --pair XAUUSD --tf M30 --no-telegram

echo All backtests complete.
pause
