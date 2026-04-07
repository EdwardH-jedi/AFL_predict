@echo off
rem AFL Predict - Weekly Model Training (매주 일요일 03:00)
rem RTX 5080 메인 컴퓨터에서 실행 권장 (NODE_ROLE=predictor)

set TASKS_DIR=%~dp0
set PROJECT=%TASKS_DIR%..\..\
cd /d "%PROJECT%"

if not exist logs mkdir logs

echo [%DATE% %TIME%] Weekly training starting >> logs\train_models.log 2>&1
call .venv\Scripts\activate.bat
python -m orchestration.jobs.train_models >> logs\train_models.log 2>&1
echo [%DATE% %TIME%] Training finished (exit %ERRORLEVEL%) >> logs\train_models.log 2>&1
