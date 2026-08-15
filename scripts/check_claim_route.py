"""Tarkistusreitin vahti: onko jokainen VAITE loydettavissa linkatulta sivulta.

MIKSI TAMA ON OLEMASSA (15.8.2026). Kirjoitin GW1-muistioon vaitteen
"beats 119 of the 161 fully fit defenders we project", verifioin sen KOODISTA
ja se oli tosi. Julkaisutarkistaja meni sille sivulle jonka olin nimennyt
tarkistusreitiksi ja mittasi:

    /fpl/expected-points on top-100, katkaisu 18.1 xP
    -> Mukiele (17.0) EI OLE SIVULLA LAINKAAN
    -> lukuja 119 ja 161 ei ole missaan
    -> sivulla on 39 DEF-rivia, ei 161

Vaite oli siis TOSI mutta ei TARKISTETTAVISSA, ja lukija olisi mennyt
katsomaan eika olisi loytanyt mitaan. Sama vika kuin 10.8:n Tavernier-tapaus.

Samassa tekstissa oli toinen mekaaninen virhe: kirjoitin Sesko 11.4 (pyoristin
11.35:sta) kun sivu sanoo 11.3 — ja 11.4 oli sivulla mutta kuului TOISELLE
pelaajalle. Lukija olisi loytanyt vaaran miehen.

Molemmat ovat koneellisesti tarkistettavia. Tekstin TYYLI ei ole, ja siksi
tama tyokalu ei kirjoita mitaan: se vain kertoo mika vaite ei kesta.

KAYTTO:
    python -m scripts.check_claim_route --url https://goaliq.app/fpl/team-news \\
        --claim "61" --claim "Mukiele" --claim "17.0" --claim "Tavernier" \\
        --claim "26.1"

    # tai tiedostosta, yksi vaite per rivi:
    python -m scripts.check_claim_route --url <url> --claims-file claims.txt

Exit 0 = kaikki loytyi nakyvasta sisallosta. Exit 1 = ainakin yksi ei.

MITA TAMA EI TEE. Se ei kerro onko luku OIKEIN mallissa — se kertoo naakko
lukija sen siina paikassa johon teksti hanet lahettaa. Ne ovat eri kysymyksia
ja tama tyokalu vastaa siihen jalkimmaiseen, koska se on se joka petti.
"""
from __future__ import annotations

import argparse
import html as _html
import re
import subprocess
import sys
from pathlib import Path

# Sarakkeet joilla on tama luokka piilotetaan kapealla ruudulla. Luku joka
# nakyy vain tyopoydalla ei ole tarkistusreitti puhelinkayttajalle, ja se puri
# 11.8 Rowanin ketjussa.
MOBILE_HIDDEN_CLASS = "m-hide"


def fetch(url: str) -> str:
    """Hae sivu subprocess-curlilla.

    EI urllibia: Cloudflare palauttaa python-clienteille 403 (sama ansa kuin
    ESPN-API:ssa, kirjattu). curl on myos se mita ihminen kayttaisi.
    """
    r = subprocess.run(["curl", "-s", "-L", url], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"curl epaonnistui: {r.returncode}")
    return r.stdout.decode("utf-8", errors="replace")


def _strip_hidden(doc: str) -> str:
    """Poista mobiilissa piilotetut solut ennen etsintaa."""
    return re.sub(
        rf'<t[dh][^>]*class="[^"]*{MOBILE_HIDDEN_CLASS}[^"]*"[^>]*>.*?</t[dh]>',
        " ", doc, flags=re.S)


def _visible_text(doc: str) -> str:
    """HTML -> nakyva teksti. Script/style pois, entiteetit auki."""
    doc = re.sub(r"<(script|style)\b.*?</\1>", " ", doc, flags=re.S | re.I)
    doc = re.sub(r"<!--.*?-->", " ", doc, flags=re.S)
    doc = re.sub(r"<[^>]+>", " ", doc)
    return re.sub(r"\s+", " ", _html.unescape(doc))


def _numerot(doc: str) -> set[float]:
    """Kaikki dokumentin numeeriset tokenit floatteina.

    Tarvitaan koska client-renderoity sivu kantaa RAAKOJA floatteja ja
    muotoilee solun vasta selaimessa: payloadissa on `4.5`, taulukossa lukee
    `4.50`. Merkkijonohaku antoi siksi EI-LOYDY luvuille jotka lukija nakee.

    🔴 EI SUBSTRING-NORMALISOINTIA. Houkutus olisi vertailla `4.5` osajonona,
    mutta se osuisi myos lukuun `14.55` ja keksisi vaitteelle katteen jota ei
    ole. Portin oma normalisointi on reika (kirjattu). Siksi tokenit poimitaan
    rajoineen ja verrataan numeroina.
    """
    out = set()
    for m in re.findall(r"-?\d+\.\d+|-?\d+", doc):
        try:
            out.add(float(m))
        except ValueError:
            pass
    return out


def check(url: str, claims: list[str]) -> list[tuple[str, str]]:
    """Palauta [(vaite, tulos)] jokaiselle vaitteelle.

    Tulokset:
      OK            loytyy palvelimen renderoimasta nakyvasta tekstista
      VAIN-TYOPOYTA loytyy, mutta vain m-hide-sarakkeesta
      VAIN-DATASSA  loytyy sivun datasta muttei renderoidusta tekstista
      EI-LOYDY      ei ole sivulla lainkaan

    🔴 `VAIN-DATASSA` LISATTIIN 15.8 KOSKA TYOKALU ANTOI VAARAN HALYTYKSEN.
    Ajoin sen `/fpl/stats`-sivulle ja se vaitti etta "Struijk" ja "4.65" eivat
    ole sivulla. Ne OVAT: sivu kantaa taulukkonsa JSONina script-lohkossa ja
    renderoi sen selaimessa. Riisun script-lohkot tarkoituksella (lukija ei
    nae niita), ja se teki client-renderoidusta sivusta nakymattoman.

    Vaara halytys on PAHEMPI kuin puuttuva tyokalu: portti joka huutaa
    turhaan opitaan ohittamaan, ja silloin se ei estä sita oikeaa virhetta
    jota varten se rakennettiin. Kolmas tila kertoo eron sen sijaan etta
    valehtelisi kumpaankin suuntaan.
    """
    doc = fetch(url)
    full = _visible_text(doc)
    mobile = _visible_text(_strip_hidden(doc))
    luvut = _numerot(doc)
    out = []
    for c in claims:
        needle = c.strip()
        if not needle:
            continue
        try:
            arvo = float(needle)
        except ValueError:
            arvo = None

        if needle in mobile:
            out.append((needle, "OK"))
        elif needle in full:
            out.append((needle, "VAIN-TYOPOYTA"))
        elif arvo is not None:
            # 🔴 NUMEERINEN VAITE EI KAYTA OSAJONOHAKUA RAAKADOKUMENTTIIN.
            # Mitattu 15.8 omalla negatiivisella kontrollilla: vaite "1.4"
            # osui osajonona datassa olevaan lukuun "1.45" ja sai katteen jota
            # sivu ei tue. Sama sokeus kuin aiemmin kirjattu substring-osuma.
            # Numerot verrataan siis TOKENEINA, ei merkkijonoina.
            #
            # Tulos on VAIN-DATASSA eika OK: luku on payloadissa (esim. `4.5`)
            # ja renderoituu soluun muodossa `4.50`, mutta se ero on juuri se
            # mita kolmas tila on olemassa kertomaan.
            out.append((needle, "VAIN-DATASSA" if arvo in luvut else "EI-LOYDY"))
        elif needle in doc:
            out.append((needle, "VAIN-DATASSA"))
        else:
            out.append((needle, "EI-LOYDY"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="sivu johon teksti linkittaa")
    ap.add_argument("--claim", action="append", default=[],
                    help="tarkistettava merkkijono (toistettavissa)")
    ap.add_argument("--claims-file", type=Path,
                    help="tiedosto jossa yksi vaite per rivi")
    a = ap.parse_args(argv)

    claims = list(a.claim)
    if a.claims_file:
        claims += [l for l in a.claims_file.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")]
    if not claims:
        print("VIRHE: anna ainakin yksi --claim tai --claims-file")
        return 2

    rows = check(a.url, claims)
    leveys = max(len(c) for c, _ in rows)
    print(f"Tarkistusreitti: {a.url}\n")
    for c, tulos in rows:
        merkki = {"OK": "  ", "VAIN-TYOPOYTA": "! ",
                  "VAIN-DATASSA": "~ ", "EI-LOYDY": "X "}[tulos]
        print(f"  {merkki}{c:<{leveys}}  {tulos}")

    puuttuu = [c for c, t in rows if t == "EI-LOYDY"]
    vain_tp = [c for c, t in rows if t == "VAIN-TYOPOYTA"]
    vain_data = [c for c, t in rows if t == "VAIN-DATASSA"]
    print()
    if vain_data:
        print(f"~ {len(vain_data)} vaitetta on sivun DATASSA muttei "
              f"palvelimen renderoimassa tekstissa: {', '.join(vain_data)}")
        print("  Sivu renderoi ne selaimessa. Lukija nakee ne, mutta TAMA "
              "tyokalu ei voi todistaa sita — avaa sivu ja katso.")
    if vain_tp:
        print(f"! {len(vain_tp)} vaitetta nakyy VAIN tyopoydalla "
              f"(m-hide-sarake): {', '.join(vain_tp)}")
    if puuttuu:
        print(f"X {len(puuttuu)} vaitetta EI OLE sivulla: {', '.join(puuttuu)}")
        print("  Lukija menisi tarkistamaan eika loytaisi mitaan. Vaihda vaite "
              "tai vaihda linkki — pehmentaminen ei auta.")
        return 1
    print("Kaikki vaitteet loytyvat sivulta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
