@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo.
    echo [错误] 未找到 Python。
    echo 请先安装 Python 3.12 并勾选 "Add Python to PATH"
    echo 下载: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
  )
  set "PY=py -3"
) else (
  set "PY=python"
)

echo.
echo ========================================
echo   OfficeLego Windows 打包
echo ========================================
echo.

echo ^>^>^> 安装依赖...
%PY% -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
  echo [错误] 依赖安装失败
  pause
  exit /b 1
)

echo ^>^>^> 开始打包（约 1-3 分钟）...
%PY% -m PyInstaller --noconfirm --clean officelego.spec
if errorlevel 1 (
  echo [错误] 打包失败
  pause
  exit /b 1
)

echo ^>^>^> 复制说明文件...
copy /Y "README-Windows.txt" "dist\OfficeLego\" >nul
copy /Y "windows_launch.bat" "dist\OfficeLego\" >nul
copy /Y "同事请看.txt" "dist\OfficeLego\" >nul

echo ^>^>^> 生成 zip...
cd dist
if exist OfficeLego-win.zip del OfficeLego-win.zip
powershell -NoProfile -Command "Compress-Archive -Path 'OfficeLego' -DestinationPath 'OfficeLego-win.zip' -Force"
if errorlevel 1 (
  echo [错误] zip 生成失败
  pause
  exit /b 1
)

echo.
echo ========================================
echo   完成！
echo ========================================
echo.
echo 安装包:
echo   %CD%\OfficeLego-win.zip
echo.
echo 同事用法：解压整个 OfficeLego 文件夹，双击 windows_launch.bat
echo.
pause
endlocal
