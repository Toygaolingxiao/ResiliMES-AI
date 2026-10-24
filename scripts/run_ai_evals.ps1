# Live AI evaluation on Nemotron through Nightshift, all arms in one go.
#
#   cd C:\code\ResiliMES-AI
#   powershell -ExecutionPolicy Bypass -File scripts\run_ai_evals.ps1
#
# Runs every investigator case, every late-lot explanation and every handover
# report (12: 4 shifts x en/zh/ja) sequentially with one progress line per arm
# (-Arms investigator|explainer|handover runs one). Results land in
# outputs\ai_eval\ (JSON per arm plus summary_nightshift.json). Partial results are
# written after each item, so a stopped run keeps what it finished.
# Needs METERLESS_BASE_URL, METERLESS_RUNTIME_TOKEN and NEMOTRON_MODEL in the
# environment or .env; the token is never printed.
param(
    [string]$Arms = "all",
    [double]$Temperature = 0.2
)
$ErrorActionPreference = "Stop"
$env:NO_COLOR = "1"
$env:RESILIMES_MODE = "live"
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path -Parent $PSScriptRoot)
$started = Get-Date
python -m resilimes.insight.study $Arms --provider nightshift --temperature $Temperature
$code = $LASTEXITCODE
$took = (Get-Date) - $started
$summaryPath = "outputs\ai_eval\summary_nightshift.json"
if (Test-Path $summaryPath) {
    $check = (Get-Content $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json).model_check
    if ($check -and $check.all_nemotron) {
        Write-Host "MODEL CHECK OK: every response came from a Nemotron model."
    } else {
        Write-Host "MODEL CHECK FLAG: some responses did not come from Nemotron (or none recorded). See model_check / model_audit in $summaryPath" -ForegroundColor Yellow
    }
}
Write-Host ("run_ai_evals finished in {0:hh\:mm\:ss}, exit {1}. Results: outputs\ai_eval\summary_nightshift.json" -f $took, $code)
exit $code
