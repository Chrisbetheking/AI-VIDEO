@echo off
cd /d C:\ai-video-worker\collector-local
call .venv\Scripts\activate
set /p LIMIT=请输入本次测试账号数量，默认1：
if "%LIMIT%"=="" set LIMIT=1
python run_all.py --headful --dry-run --limit %LIMIT% --no-delay
pause
