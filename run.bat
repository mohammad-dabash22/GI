@echo off
cd /d "%~dp0"
set PATH=C:\Users\TG775DU\AppData\Local\Programs\Python\Python312;C:\Users\TG775DU\AppData\Local\Programs\Python\Python312\Scripts;%PATH%

echo Installing dependencies...
pip install -q -r requirements.txt
echo.
echo ============================================
echo   Forensic Graph Intelligence PoC
echo ============================================
echo.
echo   Open your browser at: http://localhost:8050
echo   Press Ctrl+C to stop the server.
echo.
start http://localhost:8050
python app.py
pause
