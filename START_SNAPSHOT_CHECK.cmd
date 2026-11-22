@echo off
cd /d "%~dp0"
python demo_server.py --host 127.0.0.1 --port 8767 --open
pause
