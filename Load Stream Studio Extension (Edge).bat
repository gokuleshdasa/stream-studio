@echo off
setlocal
title Load Stream Studio Extension into Edge

rem Prefer the installed copy; fall back to a chrome-extension folder next to this file.
set "EXTDIR=%ProgramFiles%\Stream Studio\chrome-extension"
if not exist "%EXTDIR%\manifest.json" set "EXTDIR=%~dp0chrome-extension"
if not exist "%EXTDIR%\manifest.json" set "EXTDIR=%~dp0streamstudio\chrome-extension"

echo ============================================================
echo   Load the Stream Studio Download button into Microsoft Edge
echo ============================================================
echo.
echo Extension folder:
echo     %EXTDIR%
echo.

if not exist "%EXTDIR%\manifest.json" (
  echo [!] Could not find the chrome-extension folder. Put this .bat next to it.
  pause & exit /b 1
)

rem Put the folder path on the clipboard so you can paste it in the picker.
<nul set /p "=%EXTDIR%" | clip
echo (Folder path copied to clipboard - press Ctrl+V in the folder picker.)
echo.
echo Opening the folder and Edge's Extensions page...
start "" explorer "%EXTDIR%"

set "EDGE="
for %%P in (
  "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
) do if exist "%%~P" set "EDGE=%%~P"

if defined EDGE (
  start "" "%EDGE%" "edge://extensions"
) else (
  echo Could not find Edge automatically. Open Edge and go to:  edge://extensions
)

echo.
echo NEXT - in Edge's Extensions page:
echo    1^) Turn ON "Developer mode"  (left-side toggle^)
echo    2^) Click "Load unpacked"
echo    3^) Paste the path with Ctrl+V (or pick the folder that opened^) and select it
echo    4^) Browse any supported site (YouTube, SoundCloud, Vimeo...^) -
echo       a "Download this media" button appears automatically.
echo.
echo Keep Stream Studio running (it's in your system tray) for the button to work.
echo.
pause
