@echo off
rem 批次四①:经看门狗拉起服务——进程退出自动退避重启,日志 data\logs\watchdog.log
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" "..\scripts\watchdog.py" %1
