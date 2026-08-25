# fix_task_paths_rtx5080.ps1
# 저장소가 codex-hub 하위로 이동한 뒤 옛 경로를 가리키던 AFL_* 작업들을 정리한다.
# 반드시 "관리자 PowerShell"에서 실행:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   & "C:\Users\<you>\AFL_predict\ops\fix_task_paths_rtx5080.ps1"
#
# 하는 일:
#   1. 옛 경로를 가리키는 AFL_* 작업 전부 제거
#      (AFL_DailyPipeline_Predictor, AFL_NotifyBets, AFL_WeeklyTrain, AFL_WeeklyBacktest)
#   2. 현재 경로 기준으로 standalone 구성 재등록:
#      AFL_FetchWeather   매일 07:00
#      AFL_DailyPipeline  매일 08:00  (NODE_ROLE=standalone → 수집+추론 전체 실행)
#      AFL_WeeklyTrain    일요일 03:00
#      AFL_WeeklyBacktest 일요일 04:00
#   AFL_NotifyBets는 재등록하지 않는다 — notify는 일일 파이프라인 안에서 1회 실행된다.

$ProjectDir = Split-Path $PSScriptRoot -Parent
$Python     = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir     = Join-Path $ProjectDir "logs"

if (-not (Test-Path $Python)) { Write-Host "ERROR: $Python 없음 — venv부터 만드세요." -ForegroundColor Red; exit 1 }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# 1) 옛 작업 제거
foreach ($name in @("AFL_DailyPipeline_Predictor", "AFL_NotifyBets", "AFL_WeeklyTrain", "AFL_WeeklyBacktest", "AFL_DailyPipeline", "AFL_FetchWeather")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "  제거: $name"
    }
}

# 2) 재등록
function Register-AflTask {
    param([string]$Name, [string]$Arguments, $Trigger, [string]$Desc)
    $action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $ProjectDir
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "  등록: $Name  [$Desc]" -ForegroundColor Green
}

Register-AflTask -Name "AFL_FetchWeather"   -Arguments "-m orchestration.jobs.fetch_weather" `
    -Trigger (New-ScheduledTaskTrigger -Daily -At "07:00") -Desc "매일 07:00"
Register-AflTask -Name "AFL_DailyPipeline"  -Arguments "-m orchestration.daily_pipeline --triggered-by cron" `
    -Trigger (New-ScheduledTaskTrigger -Daily -At "08:00") -Desc "매일 08:00"
Register-AflTask -Name "AFL_WeeklyTrain"    -Arguments "-m orchestration.jobs.train_models" `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00") -Desc "일요일 03:00"
Register-AflTask -Name "AFL_WeeklyBacktest" -Arguments "-m orchestration.jobs.run_backtest --mode expanding" `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "04:00") -Desc "일요일 04:00"

Write-Host ""
Write-Host "완료. 확인:" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object TaskName -like 'AFL_*' | ForEach-Object {
    $i = $_ | Get-ScheduledTaskInfo
    Write-Host ("  {0,-22} Next: {1}" -f $_.TaskName, $i.NextRunTime)
}
Write-Host ""
Write-Host "즉시 테스트: Start-ScheduledTask -TaskName AFL_DailyPipeline"
