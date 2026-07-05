# Task Scheduler -käynnistin: FPL-projektioiden viikottainen refresh
# (Phase 0 CS%/FDR + Phase 1 xP samassa jobissa "GoalIQ-FPL-Phase0-refresh").
# Lokit per päivä -> logs\fpl_phase0_YYYY-MM-DD.log + logs\fpl_xp_YYYY-MM-DD.log.
# Sanity-gate FAIL (exit 2) -> JSONia ei kirjoitettu. EI auto-pushia:
# onnistunut ajo tulostaa git-komennot lokiin (sama konventio kuin WC-refresh).
# Exit-koodi = pahin kahdesta ajosta (kumpikin builderi on itsenäinen fail-safe).
# TODO(kaudenvaihto): kun FPL-API tarjoilee 26/27-GW-deadlinet, tihennä ajastus
# deadline-ikkunoihin (GW:n jälkeen + ennen deadlinea).
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force logs | Out-Null

$log0 = "logs\fpl_phase0_$(Get-Date -Format yyyy-MM-dd).log"
& .\.venv\Scripts\python.exe -m scripts.build_fpl_phase0 *>> $log0
$exit0 = $LASTEXITCODE

$log1 = "logs\fpl_xp_$(Get-Date -Format yyyy-MM-dd).log"
& .\.venv\Scripts\python.exe -m scripts.build_fpl_xp *>> $log1
$exit1 = $LASTEXITCODE

exit [Math]::Max($exit0, $exit1)
