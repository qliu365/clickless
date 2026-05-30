@echo off
cd /d "%~dp0"

echo ========================================
echo   OfficeLego Mouse Self-Test
echo   OfficeLego 鼠标自检
echo ========================================
echo.
echo In 3 seconds the mouse should move to screen center.
echo 3 秒后鼠标应移到屏幕中间。
echo Do not touch the mouse / 请不要动鼠标
echo.

if not exist "OfficeLego.exe" (
    echo [ERROR] OfficeLego.exe not found
    pause
    exit /b 1
)

timeout /t 3 /nobreak >nul
"OfficeLego.exe" --self-test
echo.
echo Exit code: %ERRORLEVEL%
echo If FAIL, send self-test.log to support.
echo 若失败，把 AppData\Local\OfficeLego\self-test.log 发给技术支持
echo.
pause
