@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [AI 信息情报官] 发送测试消息到飞书群...
echo.
".venv\Scripts\python.exe" main.py --test-push
echo.
pause
