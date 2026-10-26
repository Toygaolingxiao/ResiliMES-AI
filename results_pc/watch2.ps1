Set-Location C:\code\ResiliMES-AI
while (-not (Select-String -Path results_pc\watch.log -Pattern 'live eval done' -Quiet -ErrorAction SilentlyContinue)) { Start-Sleep 60 }
git pull --ff-only origin main *> results_pc\pull2.log
"investigator v2 start $(Get-Date -Format s) $(git log --oneline -1)" | Out-File results_pc\watch.log -Append
powershell -ExecutionPolicy Bypass -File scripts\run_ai_evals.ps1 -Arms investigator *> results_pc\investigator_v2.log
Copy-Item outputs\ai_eval\investigator_nightshift.json results_pc\investigator_nightshift_v2.json -Force
"investigator v2 done $(Get-Date -Format s)" | Out-File results_pc\watch.log -Append
