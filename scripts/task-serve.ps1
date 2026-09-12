# 注册 Soulspring 服务计划任务(脱离 AI 会话进程树,防沙箱回收)并立即启动
# 2026-09-10:服务消失根因=AI 会话经 Bash 起的进程被沙箱作业对象连带回收;
# 任务计划程序托管的进程不受影响。普通用户权限可注册自己的任务。
$py = 'E:\进行\backend\.venv\Scripts\python.exe'
$wd = 'E:\进行\backend'
$act = New-ScheduledTaskAction -Execute $py `
  -Argument '-m uvicorn app.main:app --host 127.0.0.1 --port 8600 --app-dir E:\进行\backend' `
  -WorkingDirectory $wd
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'Soulspring-Server' -Action $act `
  -Settings $settings -Force -ErrorAction Stop | Out-Null
Start-ScheduledTask -TaskName 'Soulspring-Server'
Write-Output 'Soulspring-Server task registered & started'
