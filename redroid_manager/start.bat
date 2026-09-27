@echo off
title Redroid Multi-Instance Studio
echo ========================================================
echo   Starting Redroid Multi-Instance Studio Dashboard
echo ========================================================

cd /d "%~dp0"
python -m pip install -r requirements.txt
echo.
echo [*] Launching FastAPI Web Server on http://127.0.0.1:8000 ...
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
pause
