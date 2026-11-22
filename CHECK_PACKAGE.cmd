@echo off
cd /d "%~dp0"
python tools/preflight.py
if errorlevel 1 exit /b 1
echo Package files verified. Install requirements-lock.txt before --runtime checks.
