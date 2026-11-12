@echo off
title Game Pad Remote - PC host
cd /d "%~dp0"
where py >nul 2>nul && (py -3 host.py %* & goto :end)
where python >nul 2>nul && (python host.py %* & goto :end)
echo Python 3 is not installed. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
:end
pause
