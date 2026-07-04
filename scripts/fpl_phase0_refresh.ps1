# Task Scheduler -käynnistin: FPL Phase 0 -projektion viikottainen refresh.
# Loki per päivä -> logs\fpl_phase0_YYYY-MM-DD.log.
# Sanity-gate FAIL (exit 2) -> JSONia ei kirjoitettu. EI auto-pushia:
# onnistunut ajo tulostaa git-komennot lokiin (sama konventio kuin WC-refresh).
# TODO(kaudenvaihto): kun FPL-API tarjoilee 26/27-GW-deadlinet, tihennä ajastus
# deadline-ikkunoihin (GW:n jälkeen + ennen deadlinea).
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\fpl_phase0_$(Get-Date -Format yyyy-MM-dd).log"
& .\.venv\Scripts\python.exe -m scripts.build_fpl_phase0 *>> $log
exit $LASTEXITCODE
