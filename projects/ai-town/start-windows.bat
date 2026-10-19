@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Starting AI Town. Keep this window open while using the town.
echo Your browser will open automatically. No API key is needed.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    py -3 server.py --port 0 --open-browser
    goto done
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    python server.py --port 0 --open-browser
    goto done
)
echo Python 3.10 or newer was not found.
echo Install Python from https://www.python.org/downloads/
echo Then run this launcher again. No extra Python packages are required.
:done
echo.
pause
