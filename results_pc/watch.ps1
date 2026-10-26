Set-Location C:\code\ResiliMES-AI
$env:PYTHONIOENCODING='utf-8'; $env:NO_COLOR='1'; $env:RESILIMES_MODE='live'
while ($true) {
  try { $n = ((Get-Content outputs\ai_eval\explainer_nightshift.json -Raw -Encoding UTF8 | ConvertFrom-Json).rows).Count } catch { $n = 0 }
  if ($n -ge 12) { break }
  Start-Sleep 30
}
Copy-Item outputs\ai_eval\explainer_nightshift.json results_pc\explainer_nightshift_12.json -Force
Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'resilimes.insight.study|run_ai_evals|run_live_eval' -and $_.ProcessId -ne $PID } | % { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
"explainer stopped at $n rows $(Get-Date -Format s)" | Out-File results_pc\watch.log
python -m resilimes.insight.study handover --provider nightshift --temperature 0.2 *> results_pc\handover.log
"handover done $(Get-Date -Format s)" | Out-File results_pc\watch.log -Append
python scripts\run_live_eval.py *> results_pc\live_eval.log
"live eval done $(Get-Date -Format s)" | Out-File results_pc\watch.log -Append
