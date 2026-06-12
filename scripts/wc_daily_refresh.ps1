# Task Scheduler -käynnistin: WC-mallin päivittäinen virkistystarkistus.
# Loki per päivä -> logs\wc_refresh_YYYY-MM-DD.log (hiljaiset päivät = tyhjä loki).
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\wc_refresh_$(Get-Date -Format yyyy-MM-dd).log"
& .\.venv\Scripts\python.exe -m scripts.wc_daily_refresh *>> $log
exit $LASTEXITCODE
