@echo off
chcp 65001 >nul
REM 请双击本文件启动（确保与 _internal 文件夹在同一目录）
cd /d "%~dp0"

if not exist "Clickless.exe" (
    echo [错误] 找不到 Clickless.exe
    echo 请解压完整的 Clickless-win.zip，不要只复制单个 exe。
    pause
    exit /b 1
)

if not exist "_internal\" (
    echo [错误] 找不到 _internal 文件夹
    echo 必须保留 Clickless.exe 和 _internal 在一起，不能删。
    pause
    exit /b 1
)

REM 直接运行（不用 start），便于排查闪退
"Clickless.exe"
