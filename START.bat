@echo off
REM One click: opens the job-search page in the browser (no console window).
REM The page scans all sources (~10 min) with live progress, then lists the jobs.
set PYW=C:\Users\segev\.conda\envs\resume-tailor\pythonw.exe
if not exist "%PYW%" (
    echo Error: Python not found at %PYW%
    pause
    exit /b 1
)
cd /d "%~dp0"
start "" "%PYW%" TOOL_FILES\engine\web_app.py --scan
