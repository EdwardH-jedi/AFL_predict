# AFL Predict - Windows Task Scheduler Setup (predictor / RTX 5080)
# Run from project root:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\ops\setup_scheduler_predictor.ps1

# Derive project root from this script's location (ops\ -> parent)
$ProjectDir = Split-Path $PSScriptRoot -Parent
$Python     = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir     = Join-Path $ProjectDir "logs"

Write-Host "ProjectDir: $ProjectDir"
Write-Host "Python    : $Python"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "[OK] Created logs folder"
}

if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] Python not found: $Python"
    Write-Host "        Step 1: python -m venv .venv"
    Write-Host "        Step 2: .venv\Scripts\activate.bat"
    Write-Host "        Step 3: pip install -r requirements.txt"
    exit 1
}

Write-Host ""
Write-Host "Registering AFL Predict scheduled tasks (predictor role)..."
Write-Host ""

function Register-AflTask {
    param(
        [string]$TaskName,
        [string]$Description,
        [string]$Arguments,
        $Trigger
    )

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "  [UPDATE] $TaskName"
    } else {
        Write-Host "  [NEW]    $TaskName"
    }

    $Action = New-ScheduledTaskAction `
        -Execute $Python `
        -Argument $Arguments `
        -WorkingDirectory $ProjectDir

    $Settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -RestartCount 1 `
        -RestartInterval (New-TimeSpan -Minutes 10) `
        -StartWhenAvailable `
        -DontStopIfGoingOnBatteries `
        -WakeToRun:$false

    $Principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $Description `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Force | Out-Null

    Write-Host "         Args: $Arguments"
}

# Task 1: Daily pipeline - 09:30
Write-Host "[Task 1] Daily pipeline - 09:30 daily"
$t1 = New-ScheduledTaskTrigger -Daily -At "09:30"
Register-AflTask `
    -TaskName    "AFL_DailyPipeline_Predictor" `
    -Description "AFL Predict daily pipeline (build features + recommendations)" `
    -Arguments   "-m orchestration.daily_pipeline --triggered-by cron" `
    -Trigger     $t1

# Task 2: Weekly model retrain - Sunday 03:00
Write-Host ""
Write-Host "[Task 2] Weekly model retrain - Sunday 03:00"
$t2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"
Register-AflTask `
    -TaskName    "AFL_WeeklyTrain" `
    -Description "AFL Predict weekly model retrain (XGBoost + Ensemble)" `
    -Arguments   "-m orchestration.jobs.train_models" `
    -Trigger     $t2

# Task 3: Bet notifications - 10:00
Write-Host ""
Write-Host "[Task 3] Bet notifications - 10:00 daily"
$t3 = New-ScheduledTaskTrigger -Daily -At "10:00"
Register-AflTask `
    -TaskName    "AFL_NotifyBets" `
    -Description "AFL Predict daily bet notification" `
    -Arguments   "-m orchestration.jobs.notify_bets" `
    -Trigger     $t3

# Summary
Write-Host ""
Write-Host "========================================================"
Write-Host "Done. Registered AFL tasks:"
Write-Host "========================================================"

Get-ScheduledTask | Where-Object { $_.TaskName -like "AFL_*" } | ForEach-Object {
    $taskName = $_.TaskName
    $info = $_ | Get-ScheduledTaskInfo
    if ($info.NextRunTime) {
        $nextRun = $info.NextRunTime.ToString("yyyy-MM-dd HH:mm")
    } else {
        $nextRun = "N/A"
    }
    Write-Host ("  {0,-35} NextRun: {1}" -f $taskName, $nextRun)
}

Write-Host ""
Write-Host "To test:"
Write-Host "  Start-ScheduledTask -TaskName 'AFL_DailyPipeline_Predictor'"
Write-Host "  Get-Content '$LogDir\pipeline.log' -Tail 30"
