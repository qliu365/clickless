# Windows 安装包虚拟冒烟测试（GitHub Actions / 本地 Windows）
$ErrorActionPreference = "Stop"

$AppDir = Join-Path $PSScriptRoot "dist\Clickless"
if (-not (Test-Path $AppDir)) {
    throw "Build output not found: $AppDir (run pyinstaller first)"
}

$Required = @(
    "Clickless.exe",
    "_internal",
    "START.bat",
    "windows_launch.bat",
    "README-Windows.txt"
)
foreach ($name in $Required) {
    $path = Join-Path $AppDir $name
    if (-not (Test-Path $path)) {
        throw "Missing required item: $name"
    }
}
Write-Host "[OK] package files present"

$bat = Get-Content (Join-Path $AppDir "START.bat") -Raw
foreach ($needle in @("Clickless.exe", "_internal", "tasklist")) {
    if ($bat -notmatch [regex]::Escape($needle)) {
        throw "START.bat missing: $needle"
    }
}
Write-Host "[OK] START.bat content"

Write-Host "Launching Clickless.exe for 8 seconds..."
$proc = Start-Process -FilePath (Join-Path $AppDir "Clickless.exe") `
    -WorkingDirectory $AppDir `
    -PassThru `
    -WindowStyle Normal

Start-Sleep -Seconds 8

if ($proc.HasExited) {
    $log = Join-Path $env:LOCALAPPDATA "Clickless\clickless-error.log"
    Write-Host "--- clickless-error.log ---"
    if (Test-Path $log) {
        Get-Content $log
    } else {
        Write-Host "(no log file)"
    }
    throw "Clickless.exe exited early with code $($proc.ExitCode)"
}

Write-Host "[OK] Clickless.exe still running after 8s"
Stop-Process -Id $proc.Id -Force
Write-Host "WINDOWS SMOKE OK"
