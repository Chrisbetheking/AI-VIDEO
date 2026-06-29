param(
  [string]$ProjectDir = "C:\ai-video-worker\collector-local",
  [string]$TaskName = "AI Video Collector Command Worker"
)
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d `"$ProjectDir`" && .venv\Scripts\activate && python command_worker.py"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force
Write-Host "已安装开机自启命令监听：$TaskName"
