@echo off
cd /d "%~dp0"

echo ========================================
echo   Clickless
echo ========================================
echo.

if not exist "Clickless.exe" (
    echo [ERROR] Clickless.exe not found.
    echo Extract the FULL zip. Do not copy only the exe file.
    echo.
    pause
    exit /b 1
)

if not exist "_internal\" (
    echo [ERROR] _internal folder not found.
    echo Keep Clickless.exe and _internal in the same folder.
    echo.
    pause
    exit /b 1
)

echo OK. Starting Clickless...
echo (If blocked by Windows: More info - Run anyway)
echo.
start "" "%~dp0Clickless.exe"
timeout /t 2 /nobreak >nul
exit /b 0
