# AFL Predict — daily pipeline wrapper for Windows Task Scheduler.
#
# Resolves the project root from this script's own location, so the same file
# works on any machine without editing. Register it with:
#
#   powershell -ExecutionPolicy Bypass -File <project>\ops\windows_tasks\run_daily_pipeline.ps1
#
# See ops/orchestration_24_7.md for the canonical schedule.

$ErrorActionPreference = "Continue"

# <project>\ops\windows_tasks\ -> <project>
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtualenv interpreter not found at $python. Run bootstrap.ps1 first."
    exit 1
}

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
