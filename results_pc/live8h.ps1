cd C:\code\ResiliMES-AI
$env:PYTHONIOENCODING='utf-8'; $env:NO_COLOR='1'; $env:RESILIMES_MODE='live'; $env:NEMOTRON_MAX_TOKENS='16384'
"start $(Get-Date -f s)" | Out-File results_pc\live8h.marker
python scripts\run_live_eval.py --seeds 9,10,11,12,13 --horizon-h 8 --out-dir study_sim_select_live_8h *> results_pc\live_eval_8h.log
"done $(Get-Date -f s) exit $LASTEXITCODE" | Out-File results_pc\live8h.marker -Append
