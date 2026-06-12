@echo off
setlocal
title Load Stream Studio Extension

rem Prefer the installed copy; fall back to a chrome-extension folder next to this file.
set "EXTDIR=%ProgramFiles%\Stream Studio\chrome-extension"
if not exist "%EXTDIR%\manifest.json" set "EXTDIR=%~dp0chrome-extension"

echo ============================================================
echo   Load the Stream Studio "Convert this video" Chrome extension
echo ============================================================
echo.
echo Extension folder:
echo     %EXTDIR%
echo.

if not exist "%EXTDIR%\manifest.json" (
  echo [!] Could not find the chrome-extension folder.
  echo     Put this .bat next to the chrome-extension folder and try again.
  echo.
  pause
  exit /b 1
)

rem Put the folder path on the clipboard so you can paste it in the picker.
<nul set /p "=%EXTDIR%" | clip
echo (Folder path copied to clipboard - you can paste it with Ctrl+V.)
echo.
echo Opening the folder and Chrome's Extensions page...
start "" explorer "%EXTDIR%"

set "CHROME="
for %%P in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do if exist "%%~P" set "CHROME=%%~P"

if defined CHROME (
  start "" "%CHROME%" "chrome://extensions"
) else (
  echo Could not find Chrome automatically.
  echo Open Chrome and go to:  chrome://extensions
)

echo.
echo NEXT - in Chrome's Extensions page:
echo    1^) Turn ON "Developer mode"  (top-right toggle^)
echo    2^) Click "Load unpacked"
echo    3^) Paste the path with Ctrl+V (or pick the folder that just opened^)
echo    4^) Open any YouTube video - the "Convert this video" card appears
echo.
pause
