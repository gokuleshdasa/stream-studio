@echo off
setlocal
title Stream Studio - Enable Autostart

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\Stream Studio.lnk"
set "PYW=pythonw.exe"

if not exist "%STARTUP%" (
    echo Startup folder not found: %STARTUP%
    pause
    exit /b 1
)

echo Creating: %SHORTCUT%
echo Target  : %PYW% "%APP_DIR%\app.py" --autostart

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%');" ^
    "$s.TargetPath = '%PYW%';" ^
    "$s.Arguments = '\"%APP_DIR%\app.py\" --autostart';" ^
    "$s.WorkingDirectory = '%APP_DIR%';" ^
    "$s.WindowStyle = 7;" ^
    "$s.Description = 'Stream Studio (auto-start)';" ^
    "$s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo Autostart enabled. Stream Studio will start silently at next login.
    echo Delete this file to disable:  "%SHORTCUT%"
) else (
    echo.
    echo Failed to create the shortcut.
)
echo.
pause
endlocal
