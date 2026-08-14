"""Joukkuetason voimaohitukset (data/fpl_team_overrides.csv).

MIKSI TAMA ON OLEMASSA. Dixon-Coles-reittaus sovitetaan TULOKSIIN, eika se
nae siirtoikkunaa. Esikaudella se on pahimmillaan: seura voi menettaa koko
rungon, ja malli reittaa sen yha niilla tuloksilla jotka lahteneet pelaajat
tuottivat.

Mitattu 14.8.2026: Newcastle 25,2 % minuuttivaihtuvuus = liigan korkein ja
ainoa ei-nousija yli 25 %:n kynnyksen. Lahtijoina Isak (Liverpool), Bruno
Guimaraes (Arsenal), Gordon (pois liigasta) ja Tonali (Tottenham) — plus
valmentajanvaihto, jolle mallilla ei ole mitaan signaalia. Silti mallilla oli
kahdeksan Newcastle-pelaajaa yli 15 xP6:n, karjessa koko liigan paras
<= 5,5 M£ pelaaja.

🔴 MERKKISOPIMUS — LUE TAMA ENNEN KUIN LISAAT RIVIN.
Mallissa (`dixon_coles.py`):

    lam = exp(attack[koti]  + defence[vieras] + kotietu)
    mu  = exp(attack[vieras] + defence[koti])

`defence[X]` esiintyy VASTUSTAJAN maaliodotuksessa. Siksi:

    attack_delta  < 0  ->  joukkue TEKEE vahemman maaleja
    defence_delta > 0  ->  joukkue PAASTAA enemman maaleja

Eli heikentyneelle joukkueelle: **attack negatiivinen, defence POSITIIVINEN.**
Vaara merkki defencessa parantaisi juuri sita joukkuetta jota yritit heikentaa.

🔴 VAISTYY ITSESTAAN. Reittaus sovitetaan tuloksiin, joten kun 26/27-otteluita
kertyy, malli korjaa itsensa ilman tata tiedostoa. Ohitus on siis
VALIAIKAINEN silta esikauden yli — ei pysyva korjaus. Siksi `review_by` on
PAKOLLINEN ja **vanhentunutta riviä EI SOVELLETA**: se ohitetaan aanekkaasti.
Pelaajaohituksissa `review_by` on dokumentaatiota; tassa se on portti, koska
tama rivi liikuttaa jokaista seuran pelaajaa kerralla.

🔴 KOLMAS SARAKE `attack_mult` (14.8.2026) — LUE MIKSI.
`attack_delta` EI KOSKAAN yllä pelaajien maaliodotukseen. Se ei ole heikko
vaikutus vaan nolla, ja syy on rakenteellinen:

    goals    = rates["xg90"] * share * goal_mult * GOAL_PTS   (fpl_xp.py:762)
    goal_mult = lam(t, vastustaja) / lam_avg[t]               (fpl_context.py:239)

`lam_avg[t]` on saman joukkueen keskiarvo kaikkia muita vastaan, joten
`attack[t] += d` kertoo seka osoittajan etta nimittajan luvulla `exp(d)` ja
kerroin **supistuu pois tasmalleen**. Mitattu: Newcastlen hyokkaysvoiman
leikkaus ~18 %:lla jatti Osulan `goals`-komponentin lukemaan 1,09 -> 1,09.

Se on tarkoituksellista: `goal_mult` kertoo onko tama hyva VIIKKO taman
joukkueen pelaajalle, ei kuinka hyva joukkue on. Absoluuttinen taso tulee
pelaajan omasta `xg90`:sta, eika mikaan saada sita kun joukkue pelaajan
ymparilta muuttuu.

`attack_mult` on se saato: se kertoo seuran JOKAISEN pelaajan `xg90`:n JA
`xa90`:n. Molemmat, koska seuran maalimaaran lasku laskee syottoja
identiteetin nojalla (jokaisella maalilla on korkeintaan yksi syotto).
Pelaajatason vastine (`xg_mult`) koskee vain `xg90`:ta, koska yksittaisen
pelaajan syotot eivat ole sama asia kuin hanen maalintekonsa.

Kaytannossa: `attack_delta` = "vastustajat saavat helpomman ottelun",
`attack_mult` = "taman seuran pelaajat tekevat vahemman maaleja". Jos haluat
jalkimmaisen, `attack_delta` EI riita — se ei tee sita lainkaan.

Rajat: |delta| <= MAX_DELTA, attack_mult valilla [MULT_MIN, MULT_MAX].
Kirjoitusvirhe ei saa tuhota projektiota.
"""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_PATH = ROOT / "data" / "fpl_team_overrides.csv"

# log-avaruudessa: 0.25 ~ +28 % / -22 % maaleja. Kaytannon ylaraja
# kasisaadolle; sita isompi muutos ei ole enaa "silta" vaan uusi malli.
MAX_DELTA = 0.25

# `attack_mult` liikuttaa seuran JOKAISEN pelaajan maaliodotusta, joten sen
# rajat ovat tiukemmat kuin pelaajatason vastineella (0.25..2.0). Puolittaminen
# tai puolitoistakertaistaminen kerralla koko rungolle on jo raju kasisaato.
MULT_MIN, MULT_MAX = 0.5, 1.5


def load_team_overrides(path: Path | None = None,
                        today: _dt.date | None = None) -> tuple[dict, list[str]]:
    """(team -> {"attack": float, "defence": float, "reason", "review_by"}, varoitukset).

    Puuttuva tai rikkinainen tiedosto -> tyhja dict. Ohituksen puuttuminen ei
    saa KOSKAAN kaataa projektioajoa: ilman sita malli on tasmalleen se mika
    se oli ennen tata mekanismia.
    """
    p = path or OVERRIDES_PATH
    today = today or _dt.date.today()
    out: dict[str, dict] = {}
    warnings: list[str] = []
    if not p.exists():
        return out, warnings
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in fh if not r.lstrip().startswith("#")]
        for r in csv.DictReader(rows):
            team = (r.get("team") or "").strip()
            if not team:
                continue
            try:
                atk = float(str(r.get("attack_delta", "0") or 0).strip())
                dfc = float(str(r.get("defence_delta", "0") or 0).strip())
            except (TypeError, ValueError):
                warnings.append(f"{team}: delta ei ole luku, rivi ohitettu")
                continue
            if abs(atk) > MAX_DELTA or abs(dfc) > MAX_DELTA:
                warnings.append(
                    f"{team}: |delta| > {MAX_DELTA}, rivi ohitettu "
                    f"(attack {atk}, defence {dfc})")
                continue
            raw_mult = str(r.get("attack_mult") or "").strip()
            mult = 1.0
            if raw_mult:
                try:
                    mult = float(raw_mult)
                except ValueError:
                    warnings.append(f"{team}: attack_mult ei ole luku, rivi ohitettu")
                    continue
                if not MULT_MIN <= mult <= MULT_MAX:
                    warnings.append(
                        f"{team}: attack_mult {mult} rajojen "
                        f"[{MULT_MIN}, {MULT_MAX}] ulkopuolella, rivi ohitettu")
                    continue
            review = (r.get("review_by") or "").strip()
            if not review:
                warnings.append(f"{team}: review_by puuttuu, rivi ohitettu")
                continue
            try:
                due = _dt.date.fromisoformat(review)
            except ValueError:
                warnings.append(f"{team}: review_by ei ole ISO-paiva, ohitettu")
                continue
            if due < today:
                # EI HILJAISTA JATKAMISTA. Vanhentunut joukkueohitus taistelisi
                # mallia vastaan tasan silloin kun mallilla on vihdoin oikeaa
                # 26/27-dataa jonka perusteella korjata itsensa.
                warnings.append(
                    f"{team}: review_by {review} on MENNYT -> ohitusta EI "
                    f"sovelleta. Poista rivi tai paivita paiva.")
                continue
            out[team] = {"attack": atk, "defence": dfc, "attack_mult": mult,
                         "reason": (r.get("reason") or "").strip(),
                         "review_by": review}
    except Exception as e:  # pragma: no cover — luku ei saa kaataa ajoa
        return {}, [f"luku epaonnistui, jatketaan ilman: {type(e).__name__}: {e}"]
    return out, warnings


def apply_to_fit(dc, surface: str, today: _dt.date | None = None) -> list[dict]:
    """Lataa, sovella ja raportoi — YKSI polku kaikille FPL-pinnoille.

    🔴 MIKSI TAMA ON JAETTU FUNKTIO. Ohitus oli 14.8 kytketty vain
    `build_fpl_xp.py`:hyn, jolloin xP sanoi Newcastlesta yhta ja CS/FDR
    (fixture-ticker, chip-EV) toista. Repon oma ennakkotapaus varoittaa tasan
    tasta: `add_promoted_baseline` oli aikanaan KOPIOITU kahteen builderiin
    eika /api/predict kayttanyt sita lainkaan, jolloin ennuste palautti 404:n
    Coventrylle vaikka CS%/FDR tunsi seuran. Sen korjauksen opetus kirjattiin
    koodiin: "Yksi lahde = pinnat eivat voi ajautua erilleen." Sama saanto
    tassa.

    🔴 `attack_mult` EI KULJE TATA KAUTTA, eika se ole epajohdonmukaisuus.
    Se on PELAAJAVAUHDIN kerroin (`xg90`/`xa90`) eika DC-suure, ja
    CS/FDR- ja Phase 0 -pinnoilla ei ole pelaajavauhteja lainkaan. Jos haluat
    saman asian nakyvan myos fixture-tason luvuissa, se sanotaan
    `attack_delta`lla — se on juuri se sarake joka liikuttaa lambdaa.

    🔴 `/api/predict` EI KUTSU TATA. Sen ennusteet logataan pre-match
    julkiseen track recordiin, joten kasisaato siella tarkoittaisi etta
    julkaistu osumatarkkuus mittaa kasisaatoa eika mallia. Rajaus on lukittu
    porttiin (`test_the_override_never_reaches_the_graded_prediction_surface`).

    `surface` nakyy lokissa, jotta kolmen ajon tulosteet erottuvat toisistaan.
    """
    overrides, warnings = load_team_overrides(today=today)
    for w in warnings:
        print(f"::warning::[Joukkueohitus/{surface}] {w}")
    applied = apply_team_overrides(dc, overrides)
    for r in applied:
        if not r["found"]:
            # Nimikirjoitusvirhe on todennakoisin tapa saada ohitus
            # nayttamaan toimivalta tekematta mitaan.
            print(f"::error::[Joukkueohitus/{surface}] tuntematon joukkue "
                  f"{r['team']!r} — ohitus EI vaikuttanut mihinkaan")
        else:
            print(f"      joukkueohitus/{surface} {r['team']}: "
                  f"attack {r['attack_before']:+.3f} -> {r['attack_after']:+.3f}, "
                  f"defence {r['defence_before']:+.3f} -> {r['defence_after']:+.3f} "
                  f"(review_by {r['review_by']})")
    if not applied:
        # Tyhja on laillinen tila, mutta sen on nayttava: muuten "ei rivejä"
        # ja "lukija on rikki" nayttavat lokissa tasan samalta.
        print(f"      joukkueohitus/{surface}: 0 rivia voimassa")
    return applied


def apply_team_overrides(dc, overrides: dict) -> list[dict]:
    """Muokkaa dc.attack / dc.defence PAIKALLAAN. Palauttaa sovelletut rivit.

    Tuntematon joukkuenimi EI ole hiljainen ohitus: se palautuu `applied`-
    listassa `found=False`, jotta kutsuja voi huutaa. Nimikirjoitusvirhe on
    todennakoisin tapa saada ohitus nayttamaan toimivalta tekematta mitaan.
    """
    applied = []
    for team, o in overrides.items():
        found = team in getattr(dc, "attack", {})
        rec = {"team": team, "found": found,
               "attack_delta": o["attack"], "defence_delta": o["defence"],
               # attack_mult EI ole DC-suure eika sita sovelleta tassa: se
               # kertoo seuran pelaajien xg90:n ja xa90:n builderissa. Se
               # kulkee mukana jotta kutsujan ei tarvitse lukea CSV:ta uusiksi
               # eika meta joudu arvaamaan mita oli voimassa.
               "attack_mult": o.get("attack_mult", 1.0),
               "review_by": o["review_by"], "reason": o["reason"]}
        if found:
            rec["attack_before"] = dc.attack[team]
            rec["defence_before"] = dc.defence[team]
            dc.attack[team] = dc.attack[team] + o["attack"]
            dc.defence[team] = dc.defence[team] + o["defence"]
            rec["attack_after"] = dc.attack[team]
            rec["defence_after"] = dc.defence[team]
        applied.append(rec)
    return applied
