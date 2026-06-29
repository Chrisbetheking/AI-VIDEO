param(
  [string]$Time = "02:00",
  [int]$Limit = 10,
  [string]$ProjectDir = "C:\ai-video-worker\collector-local"
)
$batPath = Join-Path $ProjectDir "daily_run.bat"
$bat = @"
@echo off
cd /d $ProjectDir
call .venv\Scripts\activate
python run_all.py --headful --limit $Limit
"@
Set-Content -Path $batPath -Value $bat -Encoding ASCII
$action = New-ScheduledTaskAction -Execute $batPath
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "AI_VIDEO_DOUYIN_COLLECTOR" -Action $action -Trigger $trigger -Settings $settings -Description "AI视频增长中枢：每日抖音账号采集" -Force
Write-Host "已设置每日自动采集：$Time，每次 $Limit 个账号。任务名：AI_VIDEO_DOUYIN_COLLECTOR"
