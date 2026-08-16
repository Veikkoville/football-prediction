"""Pelaajatason ohitusten lataus (data/fpl_player_overrides.csv).

Kaksi eri ohitusta, koska mallissa on kaksi eri aukkoa:

**`p_start` — minuutit.** Minuuttimalli kayttaa priorina viime kauden
minuutteja eika erota "ei pelannut koska ei ollut tarpeeksi hyva" ja "ei
pelannut koska oli myynnissa tai loukkaantunut". Se nakee vain minuuttiluvun.

**`xg_mult` — maaliuhka (uusi 14.8.2026).** Pelaajan maaliodotus on
`rates["xg90"] * share * goal_mult * GOAL_PTS` (`fpl_xp.py:762`), ja `xg90`
tulee kokonaan hanen OMASTA xG-historiastaan. Joukkueen voima ei paase siihen
kasiksi lainkaan, ja se on rakenteellinen eika saadettava:

    goal_mult = lam(t, vastustaja) / lam_avg[t]        (fpl_context.py:239)
    lam(t, o) = exp(attack[t] + defence[o] + kotietu)

`lam_avg[t]` on saman joukkueen keskiarvo, joten `attack[t] += d` kertoo seka
osoittajan etta nimittajan luvulla `exp(d)` ja kerroin **supistuu pois
taismalleen**. Mitattu 14.8: Newcastlen hyokkaysvoiman leikkaus ~18 %:lla
jatti Osulan `goals`-komponentin lukemaan 1,09 -> 1,09 ja Thiawin 1,04 ->
1,04. Nolla muutosta, ei pieni muutos.

Se ei ole bugi: `goal_mult` vastaa kysymykseen "onko tama hyva viikko taman
joukkueen pelaajalle", ei "kuinka hyva tama joukkue on". Aukko on siina ettei
mikaan saada `xg90`:ta kun joukkue pelaajan YMPARILTA muuttuu — esim. kun
kulmien syottajat lahtevat ja keskuspuolustajan 4,8 xG:n lahde katoaa.

`xg_mult` on se saato. Se kertoo `xg90`:n ja vaikuttaa siten suoraan
`goals`-komponenttiin. Sita EI sovelleta `xa90`:hen: pelaajan omat syotot
eivat ole sama asia kuin hanen maalintekonsa. Joukkuetason vastine
(`attack_mult` tiedostossa `fpl_team_overrides.csv`) koskee molempia, koska
seuran maalimaaran lasku laskee syottoja identiteetin nojalla.

🔴 `review_by` ON PORTTI MOLEMMILLE. Vanhentunutta rivia EI sovelleta, se
ohitetaan aanekkaasti. Aiemmin `review_by` oli talla tiedostolla pelkkaa
dokumentaatiota; se yhtenaistettiin joukkueohituksen kanssa 14.8, koska
vanhentunut maaliuhkaleikkaus on tasan yhta haitallinen kuin vanhentunut
joukkueleikkaus — molemmat alkavat taistella mallia vastaan silloin kun
mallilla on vihdoin oikeaa 26/27-dataa.
"""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_PATH = ROOT / "data" / "fpl_player_overrides.csv"

# Kirjoitusvirhe (10 eika 1.0) ei saa tuhota projektiota. Rajat ovat leveat
# mutta ne sulkevat pois suuruusluokkavirheen.
XG_MULT_MIN, XG_MULT_MAX = 0.25, 2.0


def load_player_overrides(path: Path | None = None,
                          today: _dt.date | None = None) -> tuple[dict, list[str]]:
    """(player_id -> {"p_start", "xg_mult", "reason", "review_by"}, varoitukset).

    `p_start` voi olla None: rivi voi saataa pelkkaa maaliuhkaa. `xg_mult` on
    aina luku ja oletus 1.0, jotta kutsujan ei tarvitse haarautua.

    Puuttuva tai rikkinainen tiedosto -> tyhja dict. Ohitusten puuttuminen ei
    saa KOSKAAN kaataa projektioajoa: ilman niita malli on tasmalleen se mika
    se oli ennen tata mekanismia.
    """
    p = path or OVERRIDES_PATH
    today = today or _dt.date.today()
    out: dict[int, dict] = {}
    warnings: list[str] = []
    if not p.exists():
        return out, warnings
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in fh if not r.lstrip().startswith("#")]
        for r in csv.DictReader(rows):
            try:
                pid = int(str(r.get("player_id", "")).strip())
            except (TypeError, ValueError):
                continue

            raw_ps = str(r.get("p_start") or "").strip()
            ps: float | None = None
            if raw_ps:
                try:
                    ps = float(raw_ps)
                except ValueError:
                    warnings.append(f"{pid}: p_start ei ole luku, rivi ohitettu")
                    continue
                if not 0.0 <= ps <= 1.0:
                    warnings.append(
                        f"{pid}: p_start {ps} ei ole valilla 0..1, rivi ohitettu")
                    continue

            raw_mult = str(r.get("xg_mult") or "").strip()
            mult = 1.0
            if raw_mult:
                try:
                    mult = float(raw_mult)
                except ValueError:
                    warnings.append(f"{pid}: xg_mult ei ole luku, rivi ohitettu")
                    continue
                if not XG_MULT_MIN <= mult <= XG_MULT_MAX:
                    warnings.append(
                        f"{pid}: xg_mult {mult} rajojen "
                        f"[{XG_MULT_MIN}, {XG_MULT_MAX}] ulkopuolella, rivi ohitettu")
                    continue

            if ps is None and mult == 1.0:
                # Rivi joka ei tee mitaan on todennakoisesti kirjoitusvirhe,
                # ei tyhja tarkoitus. Sen hiljainen hyvaksyminen nayttaisi
                # silta etta ohitus on voimassa.
                warnings.append(
                    f"{pid}: rivi ei aseta p_startia eika xg_multia, ohitettu")
                continue

            review = (r.get("review_by") or "").strip()
            if not review:
                warnings.append(f"{pid}: review_by puuttuu, rivi ohitettu")
                continue
            try:
                due = _dt.date.fromisoformat(review)
            except ValueError:
                warnings.append(f"{pid}: review_by ei ole ISO-paiva, ohitettu")
                continue
            if due < today:
                # EI HILJAISTA JATKAMISTA. Ks. moduulin docstring.
                warnings.append(
                    f"{pid}: review_by {review} on MENNYT -> ohitusta EI "
                    f"sovelleta. Poista rivi tai paivita paiva.")
                continue

            # 🔴 `until_available` (16.8, Villen kysymys "kun pelaaja palaa
            # pelikuntoon niin xmins yms ymmartaa sen?").
            #
            # Ei ymmartanyt. Loukkaantumisen takia laskettu rivi on ratchet:
            # kun pelaaja palaa, FPL kaantyy takaisin mutta rivi pakottaa yha
            # matalaa lukua ja malli ALIARVIOI hanet. `review_by` rajaa sen
            # kalenteriin, mutta kalenteri ei tieda milloin han palaa - se voi
            # purkautua liian aikaisin tai liian myohaan.
            #
            # Rivi kertoo nyt itse ehtonsa. `until_available=1` tarkoittaa
            # "voimassa vain niin kauan kuin han on ULKONA", ja saatavuus
            # luetaan FPL:n omasta syotteesta joka pyorii joka tapauksessa.
            # Silloin paluu pelikuntoon purkaa ohituksen ITSESTAAN.
            #
            # Oletus on POIS paalta: varamiesrivit (Dubravka 0.08,
            # Mamardashvili 0.15) ovat matalia koska he eivat aloita, EIVAT
            # koska he olisivat ulkona. Niiden ei pida purkautua koskaan
            # saatavuuden perusteella. Sekoitin nama kaksi kertaa saman
            # paivan aikana; ero on se etta saatavuus ja aloittaminen ovat
            # eri suure.
            until_available = (r.get("until_available") or "").strip().lower()
            conditional = until_available in {"1", "true", "yes", "kylla"}

            out[pid] = {
                "p_start": ps,
                "xg_mult": mult,
                "reason": (r.get("reason") or "").strip(),
                "review_by": review,
                "until_available": conditional,
            }
    except Exception as e:  # pragma: no cover — luku ei saa kaataa ajoa
        return {}, [f"luku epaonnistui, jatketaan ilman: {type(e).__name__}: {e}"]
    return out, warnings
