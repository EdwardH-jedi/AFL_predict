$ErrorActionPreference = "Continue"

$projectRoot = "C:\Users\user\OneDrive\바탕 화면\AFL_predict"
$python = "C:\Users\user\OneDrive\바탕 화면\AFL_predict\.venv\Scripts\python.exe"
$logDir = Join-Path $projectRoot "logs"
$logFile = Join-Path $logDir "daily_pipeline.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot

Add-Content -Path $logFile -Value "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] START"

& $python -m orchestration.daily_pipeline --triggered-by cron *>> $logFile
$exitCode = $LASTEXITCODE
if ($null -eq $exitCode) { $exitCode = 0 }
Add-Content -Path $logFile -Value "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] EXITCODE=$exitCode"
exit $exitCode
