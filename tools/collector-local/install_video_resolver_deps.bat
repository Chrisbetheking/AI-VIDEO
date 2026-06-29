@echo off
cd /d C:\ai-video-worker\collector-local
call .venv\Scripts\activate
python -m pip install -U yt-dlp httpx python-dotenv openpyxl playwright
python -m yt_dlp --version
pause
