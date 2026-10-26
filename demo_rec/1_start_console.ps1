# 1) Start the console for recording (live Nemotron). Keep this window off camera.
cd C:\code\ResiliMES-AI
$env:PYTHONIOENCODING='utf-8'; $env:RESILIMES_MODE='auto'; $env:RESILIMES_FAB='smt2020'; $env:NEMOTRON_MAX_TOKENS='16384'
Clear-Host
Write-Host "Starting console on http://127.0.0.1:8000 ... open it in the browser when ready."
Start-Process "http://127.0.0.1:8000"
python -m resilimes serve --host 127.0.0.1 --port 8000
