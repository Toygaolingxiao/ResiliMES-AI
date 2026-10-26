Set-Location C:\code\ResiliMES-AI
$env:PYTHONIOENCODING='utf-8'; $env:NO_COLOR='1'; $env:RESILIMES_MODE='live'; $env:NEMOTRON_MAX_TOKENS='16384'
"rerun start $(Get-Date -Format s) $(git log --oneline -1) max_tokens=16384" | Out-File results_pc\rerun.log
python -m resilimes.insight.study handover --provider nightshift --temperature 0.2 *> results_pc\handover_v2.log
Copy-Item outputs\ai_eval\handover_nightshift.json results_pc\handover_nightshift_v2.json -Force
"handover done $(Get-Date -Format s)" | Out-File results_pc\rerun.log -Append
python -m resilimes.insight.study explainer --provider nightshift --temperature 0.2 --limit 12 *> results_pc\explainer_v2.log
Copy-Item outputs\ai_eval\explainer_nightshift.json results_pc\explainer_nightshift_v2.json -Force
"explainer done $(Get-Date -Format s)" | Out-File results_pc\rerun.log -Append
python scripts\run_live_eval.py *> results_pc\live_eval.log
"live eval done $(Get-Date -Format s)" | Out-File results_pc\rerun.log -Append
