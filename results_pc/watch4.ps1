Set-Location C:\code\ResiliMES-AI
while (Get-Process -Id 15176 -ErrorAction SilentlyContinue) { Start-Sleep 30 }
Copy-Item outputs\ai_eval\investigator_nightshift.json results_pc\investigator_nightshift_v2.json -Force
"investigator v2 done $(Get-Date -Format s)" | Out-File results_pc\watch3.log -Append
