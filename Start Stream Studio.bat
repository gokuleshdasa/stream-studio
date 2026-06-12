@echo off
title Stream Studio
cd /d "%~dp0"
echo Starting Stream Studio...  (opens at http://127.0.0.1:5001)
echo Close this window to stop the app.
python app.py
pause
