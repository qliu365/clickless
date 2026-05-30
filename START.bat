@echo off
cd /d "%~dp0"

echo ========================================
echo   OfficeLego
echo ========================================
echo.

if not exist "OfficeLego.exe" (
    echo [ERROR] OfficeLego.exe not found.
    echo [错误] 找不到 OfficeLego.exe
    echo Extract the FULL zip / 请解压完整 zip，不要只复制 exe
    echo.
    pause
    exit /b 1
)

if not exist "_internal\" (
    echo [ERROR] _internal folder not found.
    echo [错误] 找不到 _internal 文件夹
    echo Keep exe and _internal together / exe 和 _internal 必须在同一文件夹
    echo.
    pause
    exit /b 1
)

echo Starting OfficeLego...
echo 正在启动 OfficeLego，请稍候 3 秒...
echo.
start "" /D "%~dp0" "%~dp0OfficeLego.exe"
timeout /t 4 /nobreak >nul

tasklist /FI "IMAGENAME eq OfficeLego.exe" 2>nul | find /I "OfficeLego.exe" >nul
if errorlevel 1 (
    echo ========================================
    echo [FAILED] OfficeLego did not start.
    echo [失败] 程序没有启动成功
    echo ========================================
    echo.
    echo Try:
    echo 1. Double-click OfficeLego.exe directly
    echo    直接双击 OfficeLego.exe（不用 bat）
    echo 2. Windows blocked? Click: More info - Run anyway
    echo    被拦截？点「更多信息」-「仍要运行」
    echo 3. Allow in antivirus / 杀毒软件里选「允许」
    echo.
    set "LOG=%LOCALAPPDATA%\OfficeLego\officelego-error.log"
    echo Error log / 错误日志:
    echo %LOG%
    echo.
    if exist "%LOG%" (
        echo --- log content / 日志内容 ---
        type "%LOG%"
        echo --- end ---
    ) else (
        echo (no log yet / 还没有日志文件)
    )
    echo.
    pause
    exit /b 1
)

echo ========================================
echo [OK] OfficeLego is running.
echo [成功] OfficeLego 已启动
echo ========================================
echo.
echo Look for "OfficeLego" window on taskbar.
echo 请看任务栏或桌面上的 OfficeLego 窗口（红按钮那个）。
echo.
echo You can close this black window now.
echo 这个黑窗口可以关掉了。
echo.
timeout /t 6
exit /b 0
