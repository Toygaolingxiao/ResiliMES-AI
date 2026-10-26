# 2) Shot 7: one real request, shows only model id / request id / advice_only. No secrets.
$lots = Invoke-RestMethod "http://127.0.0.1:8000/api/ai/explainer/lots?seed=1"
$lot = "Init_Lot_6_2"
$ids = @($lots | ConvertTo-Json -Depth 20 | Select-String -Pattern '"(Init_Lot_[^"]+)"' -AllMatches | ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value })
if ($ids.Count -gt 0 -and -not ($ids -contains $lot)) { $lot = $ids[0] }
$body = @{ lot_id = $lot; seed = 1; lang = "en" } | ConvertTo-Json
Write-Host "> POST http://127.0.0.1:8000/api/ai/explain  {lot_id: $lot, seed: 1}   (live request via Meterless Nightshift, waiting for Nemotron...)"
$r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/ai/explain" -ContentType "application/json" -Body $body -TimeoutSec 900
function Find-Key($o, [string[]]$names, $acc) {
  if ($null -eq $o) { return }
  if ($o -is [System.Management.Automation.PSCustomObject]) {
    foreach ($p in $o.PSObject.Properties) { if ($names -contains $p.Name -and -not $acc.Contains($p.Name)) { $acc[$p.Name] = $p.Value }; Find-Key $p.Value $names $acc }
  } elseif ($o -is [System.Collections.IEnumerable] -and -not ($o -is [string])) { foreach ($x in $o) { Find-Key $x $names $acc } }
}
$acc = [ordered]@{}
Find-Key $r @('explanation','fact_ok','response_models','mocked','advice_only') $acc
Write-Host ""
Write-Host "--- Nemotron explanation ---" -ForegroundColor Cyan
$e = $acc['explanation']; if ($e -isnot [string]) { $e = $e | ConvertTo-Json -Depth 10 }
Write-Host $e
Write-Host ""
Write-Host "--- proof of live call ---" -ForegroundColor Cyan
foreach ($k in 'response_models','mocked','fact_ok','advice_only') { if ($acc.Contains($k)) { Write-Host ("{0}: {1}" -f $k, (($acc[$k] | ConvertTo-Json -Compress))) } }

