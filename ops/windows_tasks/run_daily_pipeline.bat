@echo off
rem AFL Predict - Daily Pipeline
rem 이 파일 위치 기준으로 프로젝트 루트를 자동 감지합니다.

rem 이 배치 파일의 위치: <project>\ops\windows_tasks\
rem 프로젝트 루트:        <project>\
set TASKS_DIR=%~dp0
set PROJECT=%TASKS_DIR%..\..\
cd /d "%PROJECT%"

if not exist logs mkdir logs

echo [%DATE% %TIME%] Daily pipeline starting >> logs\pipeline_cron.log 2>&1
call .venv\Scripts\activate.bat
python -m orchestration.daily_pipeline --triggered-by cron >> logs\pipeline_cron.log 2>&1
echo [%DATE% %TIME%] Pipeline finished (exit %ERRORLEVEL%) >> logs\pipeline_cron.log 2>&1
