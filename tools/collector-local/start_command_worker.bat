@echo off
cd /d C:\ai-video-worker\collector-local
call .venv\Scripts\activate
python command_worker.py
pause
