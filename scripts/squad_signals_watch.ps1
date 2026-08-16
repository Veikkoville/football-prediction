# Task Scheduler -kaynnistin: SQUAD-SIGNALS-vahti (16.8.2026).
#
# 🔴 MIKSI TAMA ON OLEMASSA. Vahti rakennettiin 16.8 ja se toimi: toinen
# ajo samana paivana tuotti nelja oikeaa liputusta livesta datasta
# (Joelinton FPL 100 -> 0, Meunier a -> d). Sen jalkeen sita ei ajanut
# kukaan. Vahti jota kukaan ei aja ei ole vahti, ja se on sama vikaluokka
# kuin endpoint jota kukaan ei kutsu.
#
# 🔴 EI GITHUB-RUNNERILTA. FPL-suuntaiset kutsut on estetty GH:n
# IP-avaruudesta (kirjattu tapaus), joten tama ajetaan talta koneelta.
#
# Vahti vertaa uutta bootstrapia levylla olevaan lumikuvaan, joten AJON
# VALI ON OSA MITTARIA: liian harvoin ajettuna kaksi muutosta kumoavat
# toisensa lumikuvassa eika kumpikaan nay. Kahdesti paivassa on tiheampi
# kuin FPL:n oma paivitystahti hinnoille ja statuksille.
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force logs | Out-Null

$log = "logs\squad_signals_$(Get-Date -Format yyyy-MM-dd).log"
# 🔴 `*>> $log` kirjoittaa UTF-16:ta tassa ymparistossa, ja UTF-16-loki ei
# grepattavissa: ensimmainen ajo tuotti rivin jossa jokaisen kirjaimen
# valissa oli nollatavu. Loki jota ei voi hakea on sama kuin loki jota ei
# ole. Kaytetaan Out-Filea eksplisiittisella koodauksella.
$stamp = "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
$out = & .\.venv\Scripts\python.exe -m scripts.squad_signals_watch 2>&1
$code = $LASTEXITCODE
@($stamp) + $out | Out-File -Append -Encoding utf8 $log
exit $code
