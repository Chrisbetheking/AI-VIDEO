@echo off
cd /d C:\ai-video-worker\collector-local
call .venv\Scripts\activate
set /p NAME=请输入账号名称关键词：
python run_all.py --headful --account "%NAME%" --limit 1 --no-delay
pause
