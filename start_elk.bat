@echo off
setlocal enabledelayedexpansion
echo Starting ELK Layout Branch on port 8053...
cd /d "%~dp0"

REM Kill anything on port 8053
netstat -ano | findstr ":8053" | findstr "LISTENING" > "%TEMP%\elk_port.txt" 2>nul
for /f "tokens=5" %%a in (%TEMP%\elk_port.txt) do (
    echo Killing PID %%a on port 8053...
    taskkill /PID %%a /F >nul 2>&1
)
del "%TEMP%\elk_port.txt" >nul 2>&1
timeout /t 2 /nobreak >nul

REM Open browser after short delay then start server
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8053"
python app_elk.py
pause
