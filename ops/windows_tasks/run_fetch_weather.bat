@echo off
rem AFL Predict - Weather Fetch (매일 07:00, 파이프라인보다 1시간 앞)

set TASKS_DIR=%~dp0
set PROJECT=%TASKS_DIR%..\..\
cd /d "%PROJECT%"

if not exist logs mkdir logs

echo [%DATE% %TIME%] Weather fetch starting >> logs\weather.log 2>&1
call .venv\Scripts\activate.bat
python -m orchestration.jobs.fetch_weather >> logs\weather.log 2>&1
echo [%DATE% %TIME%] Weather fetch finished (exit %ERRORLEVEL%) >> logs\weather.log 2>&1
