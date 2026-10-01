@echo off
rem Local Windows rebuild: refresh Python deps (incl. yt-dlp), then run build.py
rem (PyInstaller --onedir -> Inno Setup -> Setup\StreamStudio-Setup.exe).
rem build.py is the single source of truth for the build; this only updates deps.
cd /d "%~dp0"
title Stream Studio - Update and Rebuild
echo [1/3] Updating Python packages (incl. yt-dlp)...
python -m pip install --upgrade pip
python -m pip install --upgrade --pre "yt-dlp[default]" yt-dlp-ejs brotli curl_cffi flask pillow pystray pyinstaller imageio-ffmpeg deno
if errorlevel 1 ( echo Failed to update Python packages. & pause & exit /b 1 )
echo.
echo [2/3] Refreshing bundled ffmpeg / deno (delete build_assets\ffmpeg.exe / deno.exe to re-pull)...
del /q build_assets\ffmpeg.exe build_assets\deno.exe 2>nul
echo.
echo [3/3] Building...
python build.py
if errorlevel 1 ( echo Build failed. & pause & exit /b 1 )
echo.
echo DONE. Installer: Setup\StreamStudio-Setup.exe
echo Remember: bump APP_VERSION (app.py) + AppVersion (installer.iss) + CHANGELOG before publishing.
pause
