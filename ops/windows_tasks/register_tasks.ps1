# register_tasks.ps1
# AFL Predict - Windows Task Scheduler 자동 등록
#
# 사용법 (관리자 PowerShell):
#   cd "<프로젝트경로>\ops\windows_tasks"
#   .\register_tasks.ps1            # 서버용 (기본)
#   .\register_tasks.ps1 -Role predictor  # 메인(RTX 5080)용
#
# 서버 (RX 6600) : AFL_FetchWeather (매일 07:00) + AFL_DailyPipeline (매일 08:00)
# 메인 (RTX 5080): AFL_WeeklyTrain (매주 일요일 03:00) 만 등록
# 학습(AFL_WeeklyTrain)은 RTX 5080 CUDA + 로컬 아티팩트가 필요하므로 서버에 등록하지 않는다.

param(
    [string]$Role = "server"   # "server" | "predictor"
)

# ---------------------------------------------------------------------------
# 경로 자동 감지 — 이 스크립트 위치 기준으로 프로젝트 루트를 찾음
# 하드코딩 없이 어떤 머신에서도 동작
# ---------------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path   # .../ops/windows_tasks
$ProjectDir = Split-Path -Parent (Split-Path -Parent $ScriptDir) # 프로젝트 루트
$TasksDir   = $ScriptDir
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "==> AFL Predict - Task Scheduler 등록" -ForegroundColor Cyan
Write-Host "    ProjectDir : $ProjectDir"
Write-Host "    TasksDir   : $TasksDir"
Write-Host "    Role       : $Role"
Write-Host ""

# 프로젝트 경로 유효성 확인
if (-Not (Test-Path $ProjectDir)) {
    Write-Host "ERROR: 프로젝트 경로를 찾을 수 없습니다: $ProjectDir" -ForegroundColor Red
    exit 1
}
if (-Not (Test-Path $VenvPython)) {
    Write-Host "WARNING: .venv가 없습니다. 먼저 .venv\Scripts\activate.bat 후 pip install 을 실행하세요." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 배치 파일 경로에 한글/공백이 있으면 cmd /c "..." 로 래핑
# ---------------------------------------------------------------------------
function Register-AflTask {
    param(
        [string]$Name,
        [string]$BatFile,
        [string]$TriggerDesc,
        $Trigger
    )

    if (-Not (Test-Path $BatFile)) {
        Write-Host "  SKIP $Name : 배치 파일 없음 ($BatFile)" -ForegroundColor Yellow
        return
    }

    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c `"$BatFile`" >> `"$ProjectDir\logs\scheduler.log`" 2>&1" `
        -WorkingDirectory $ProjectDir

    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -StartWhenAvailable

    # 현재 로그인 사용자 권한으로 실행 (패스워드 저장 없이)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Highest

    # 기존 동명 작업 제거 후 재등록
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "  (기존 작업 제거: $Name)"
    }

    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -Principal $principal | Out-Null

    Write-Host "  OK  $Name  [$TriggerDesc]" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 로그 폴더 생성
# ---------------------------------------------------------------------------
$LogDir = Join-Path $ProjectDir "logs"
if (-Not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "  logs 폴더 생성: $LogDir"
}

# ---------------------------------------------------------------------------
# 작업 등록
# ---------------------------------------------------------------------------
if ($Role -eq "server") {
    Write-Host "-- 서버(RX 6600) 작업 등록 --" -ForegroundColor Yellow

    Register-AflTask `
        -Name "AFL_FetchWeather" `
        -BatFile (Join-Path $TasksDir "run_fetch_weather.bat") `
        -TriggerDesc "매일 07:00" `
        -Trigger (New-ScheduledTaskTrigger -Daily -At "07:00AM")

    Register-AflTask `
        -Name "AFL_DailyPipeline" `
        -BatFile (Join-Path $TasksDir "run_daily_pipeline.bat") `
        -TriggerDesc "매일 08:00" `
        -Trigger (New-ScheduledTaskTrigger -Daily -At "08:00AM")

    # 과거 버전이 서버에 등록했던 학습 작업이 남아 있으면 제거
    if (Get-ScheduledTask -TaskName "AFL_WeeklyTrain" -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName "AFL_WeeklyTrain" -Confirm:$false
        Write-Host "  (서버에서 AFL_WeeklyTrain 제거 — 학습은 RTX 5080 전용)" -ForegroundColor Yellow
    }

} elseif ($Role -eq "predictor") {
    Write-Host "-- 메인(RTX 5080) 작업 등록 --" -ForegroundColor Yellow

    Register-AflTask `
        -Name "AFL_WeeklyTrain" `
        -BatFile (Join-Path $TasksDir "run_weekly_train.bat") `
        -TriggerDesc "매주 일요일 03:00" `
        -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00AM")

} else {
    Write-Host "ERROR: -Role 은 'server' 또는 'predictor' 만 가능합니다." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 완료 메시지
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> 등록 완료!" -ForegroundColor Green
Write-Host ""
Write-Host "  확인 방법:"
Write-Host "    1. Win+R -> taskschd.msc  (작업 스케줄러 GUI)"
Write-Host "    2. 작업 우클릭 -> [실행] 으로 즉시 테스트"
Write-Host ""
Write-Host "  등록된 작업 목록 (PowerShell):"
Write-Host "    Get-ScheduledTask | Where-Object TaskName -like 'AFL_*' | Select-Object TaskName, State"
Write-Host ""
