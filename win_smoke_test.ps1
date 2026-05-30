# Windows 安装包虚拟冒烟测试（GitHub Actions / 本地 Windows）
$ErrorActionPreference = "Stop"

$AppDir = Join-Path $PSScriptRoot "dist\OfficeLego"
if (-not (Test-Path $AppDir)) {
    throw "Build output not found: $AppDir (run pyinstaller first)"
}

$Required = @(
    "OfficeLego.exe",
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
foreach ($needle in @("OfficeLego.exe", "_internal", "tasklist")) {
    if ($bat -notmatch [regex]::Escape($needle)) {
        throw "START.bat missing: $needle"
    }
}
Write-Host "[OK] START.bat content"

Write-Host "Launching OfficeLego.exe for 8 seconds..."
$proc = Start-Process -FilePath (Join-Path $AppDir "OfficeLego.exe") `
    -WorkingDirectory $AppDir `
    -PassThru `
    -WindowStyle Normal

Start-Sleep -Seconds 8

if ($proc.HasExited) {
    $log = Join-Path $env:LOCALAPPDATA "OfficeLego\officelego-error.log"
    Write-Host "--- officelego-error.log ---"
    if (Test-Path $log) {
        Get-Content $log
    } else {
        Write-Host "(no log file)"
    }
    throw "OfficeLego.exe exited early with code $($proc.ExitCode)"
}

Write-Host "[OK] OfficeLego.exe still running after 8s"
Stop-Process -Id $proc.Id -Force

Write-Host "Running mouse self-test..."
$env:OFFICELEGO_CI = "1"
$test = Start-Process -FilePath (Join-Path $AppDir "OfficeLego.exe") `
    -ArgumentList "--self-test" `
    -WorkingDirectory $AppDir `
    -PassThru `
    -Wait `
    -WindowStyle Normal
if ($test.ExitCode -ne 0) {
    $log = Join-Path $env:LOCALAPPDATA "OfficeLego\self-test.log"
    if (Test-Path $log) { Get-Content $log }
    throw "Self-test failed with exit code $($test.ExitCode)"
}
Write-Host "WINDOWS SMOKE OK"
