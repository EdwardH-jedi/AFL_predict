@echo off
rem AFL Predict - API Server 시작
rem 시작 프로그램 등록 방법:
rem   Win+R -> shell:startup -> 이 파일의 바로가기를 해당 폴더에 붙여넣기

set TASKS_DIR=%~dp0
set PROJECT=%TASKS_DIR%..\..\
cd /d "%PROJECT%"

if not exist logs mkdir logs

echo [%DATE% %TIME%] API server starting >> logs\api.log 2>&1
call .venv\Scripts\activate.bat
uvicorn api.main:app --host 0.0.0.0 --port 8000 >> logs\api.log 2>&1
