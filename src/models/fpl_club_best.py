"""Seuran paras pelaaja per positio, ennustetuilla pisteilla.

🔴 MIKSI TAMA ON JAETTU MODUULI EIKA KOMPONENTTIIN HAUDATTU LISTA.
Kaksi pintaa nayttaa nama samat rivit: jakokortti (`gen_share_card.py
club-best`) ja ilmainen sivu (`/fpl/club-best`), ja KORTIN ALATUNNISTE
OSOITTAA SIVULLE. Jos laskenta olisi kopioitu molempiin, ne voisivat ajautua
erilleen — ja silloin kortti ohjaisi lukijan sivulle todistamaan luvun joka
ei enaa tasmaa. Vaite kaatuisi tasan silla reitilla jolla se piti todistaa.

Sama vikaluokka kuin `add_promoted_baseline`, joka oli kopioituna kahteen
builderiin: "Yksi lahde = pinnat eivat voi ajautua erilleen."

KULMA. Rivin arvo ei ole pelkka ennuste vaan ERO saman seuran ja saman
position kakkoseen: onko tama seuran ainoa vaihtoehto talta paikalta vai yksi
monesta. Menneet pisteet eivat vastaa siihen kysymykseen.
"""

from __future__ import annotations

POSITIONS = ("GKP", "DEF", "MID", "FWD")

# Ero jota pienempaa ei esiteta mitattuna erona.
TIE_EPS = 0.05


def club_best_rows(players: list[dict], pos: str) -> list[dict]:
    """Seurajarjestys parhaasta huonoimpaan yhdessa positiossa.

    Palauttaa listan dicteja: club, name, price, xp, gap (float|None),
    gap_kind ("measured" | "tie" | "no_data_tie" | "no_second"), prior (bool),
    xmins, uncertain_minutes (bool).

    🔴 EI MINUUTTILATTIAA. Aiempi 60 xmins -lattia tuotti hyokkaajalistan
    jossa oli 10 seuraa 20:sta samalla kun otsikko lupasi "every club". xP
    sisaltaa jo minuutit, joten vahan pelaava nousee seuransa karkeen vain jos
    seuralla ei ole ketaan parempaa — ja se on TOSI vastaus.
    """
    by_club: dict[str, list[dict]] = {}
    for p in players:
        if p.get("pos") != pos:
            continue
        by_club.setdefault(p.get("team_short") or "???", []).append(p)

    rows = []
    for club, group in by_club.items():
        group.sort(key=lambda p: -float(p.get("xp_horizon_total") or 0.0))
        top = group[0]
        v = float(top.get("xp_horizon_total") or 0.0)
        if v <= 0:
            continue
        prior = top.get("data_basis") == "no_history"
        second = (float(group[1].get("xp_horizon_total") or 0.0)
                  if len(group) > 1 else None)
        if second is None:
            # 🔴 EI "only option". Koodi tietaa vain ettei PROJEKTIOSSA ole
            # toista rivia — 80 pelaajaa suodattuu min_xp_total-rajalla ja
            # loukkaantuneet ovat excluded-listalla. Liverpoolilla ON toinen
            # hyokkaaja (Ekitike, akillesvamma), joten "only option" olisi
            # ollut julkisesti epatosi.
            gap, kind = None, "no_second"
        elif v - second < TIE_EPS:
            # Kaksi taysin eri asiaa ei saa saada samoja sanoja: mitattu 0,02
            # pisteen ero on aito, nousijaseuran identtinen priori tarkoittaa
            # ettei mallilla ole tietoa erottaa heita.
            gap, kind = 0.0, ("no_data_tie" if prior else "tie")
        else:
            gap, kind = v - second, "measured"
        rows.append({
            "club": club,
            "name": top.get("web_name"),
            "price": float(top.get("price") or 0.0),
            "xp": v,
            "gap": gap,
            "gap_kind": kind,
            # 🔴 EHTO ON `== "no_history"`, EI `!= "pl_history"`. Jalkimmainen
            # merkitsi myos `limited_history`-pelaajat, ja selite vaittaa
            # merkitysta rivista "no Premier League games yet" — Trafford
            # (LEE) on limited_history ja hanella on 360 PL-minuuttia meidan
            # omassa tiedostossamme.
            "prior": prior,
            "xmins": float(top.get("xmins") or 0.0),
            # Luottamusindikaattori: `?` ei kata tapausta jossa pelaajalla on
            # tayi PL-historia mutta epavarmat minuutit (tyoparijako).
            "uncertain_minutes": top.get("minutes_confidence") != "high",
            "second_name": (group[1].get("web_name") if len(group) > 1 else None),
        })
    rows.sort(key=lambda r: -r["xp"])
    return rows


def gap_text(row: dict) -> str:
    """Sama sanamuoto kortilla ja sivulla."""
    kind = row["gap_kind"]
    if kind == "no_second":
        return "no 2nd projected"
    if kind == "no_data_tie":
        return "no data to separate"
    if kind == "tie":
        return "tied with next"
    return f"+{row['gap']:.1f} vs next"
