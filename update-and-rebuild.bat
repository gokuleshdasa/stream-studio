@echo off
cd /d "%~dp0"
title Stream Studio - Update and Rebuild
echo ============================================================
echo   Updating all dependencies and rebuilding the installer
echo ============================================================
echo.

echo [1/4] Updating Python packages (incl. yt-dlp - the one that matters)...
python -m pip install --upgrade pip
python -m pip install --upgrade yt-dlp flask pillow pystray pyinstaller
if errorlevel 1 ( echo Failed to update Python packages. & pause & exit /b 1 )
echo.

echo [2/4] Updating ffmpeg and refreshing the bundled copy...
winget upgrade --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements --silent
powershell -NoProfile -Command "$f = Get-ChildItem \"$env:LOCALAPPDATA\Microsoft\WinGet\Packages\" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($f) { Copy-Item $f.FullName 'build_assets\ffmpeg.exe' -Force; Write-Host ('   bundled ffmpeg: ' + $f.FullName) } else { Write-Host '   (kept existing bundled ffmpeg)' }"
echo.

echo [3/4] Rebuilding the app (.exe)...
python -m PyInstaller --noconfirm --onefile --windowed --name StreamStudio --icon build_assets\app.ico --add-data "templates;templates" --add-data "static;static" --add-binary "build_assets\ffmpeg.exe;." --add-binary "build_assets\deno.exe;." --collect-all yt_dlp --collect-all pystray --collect-all PIL --hidden-import _overlapped --hidden-import _asyncio --hidden-import asyncio app.py
if errorlevel 1 ( echo Build failed. & pause & exit /b 1 )
echo.

echo [4/4] Recompiling the installer...
"%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" installer.iss
if errorlevel 1 ( echo Installer compile failed. & pause & exit /b 1 )
echo.

echo ============================================================
echo   DONE. Fresh installer is at:
echo     Setup\StreamStudio-Setup.exe
echo.
echo   Tip: bump AppVersion in installer.iss before sharing a new
echo   build so people see it as an update.
echo ============================================================
pause
