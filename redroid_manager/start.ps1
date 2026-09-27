Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Starting Redroid Multi-Instance Studio Dashboard" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
Write-Host ""
Write-Host "[*] Launching FastAPI Web Server on http://127.0.0.1:8000 ..." -ForegroundColor Green
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
