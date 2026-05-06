"""
Pelaajien kuvat Premier Leaguen virallisesta CDN:sta.

Lahde: Fantasy Premier Leaguen julkinen API
  https://fantasy.premierleague.com/api/bootstrap-static/

API on free + ei vaadi avainta. Pelaajien valokuvat:
  https://resources.premierleague.com/premierleague/photos/players/250x250/p{photo_id}.png

photo_id loytyy bootstrap-static -vastauksesta sarakkeesta `photo`
(esim "12345.jpg" -> p12345.png).
"""

from __future__ import annotations
import unicodedata


PHOTO_BASE = "https://resources.premierleague.com/premierleague/photos/players/{size}/p{pid}.png"
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

# Sallitut kokot: 110x140, 250x250
SIZE_DEFAULT = "250x250"


def _normalize_name(s: str) -> str:
    """Aksentit pois + lowercase + poista kaksoisvalit."""
    n = "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    ).lower().strip()
    return " ".join(n.split())


_PHOTO_CACHE: dict | None = None


def _hae_fpl_data() -> dict:
    """Hae FPL-bootstrap. Cache ettei kuormita."""
    global _PHOTO_CACHE
    if _PHOTO_CACHE is not None:
        return _PHOTO_CACHE
    try:
        import requests
        r = requests.get(FPL_BOOTSTRAP_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
        _PHOTO_CACHE = data
        return data
    except Exception:
        _PHOTO_CACHE = {"elements": [], "teams": []}
        return _PHOTO_CACHE


def hae_pelaajan_kuva(nimi: str, joukkue: str | None = None,
                      size: str = SIZE_DEFAULT) -> str | None:
    """
    Etsi pelaajan kuva-URL FPL-datasta.

    Kayttaa nimi-vertailua (aksentittomana). Jos `joukkue` annettu,
    rajoittaa hakua sina joukkuepartioon.
    """
    data = _hae_fpl_data()
    elements = data.get("elements", [])
    if not elements:
        return None

    nimi_n = _normalize_name(nimi)
    if not nimi_n:
        return None

    # Mappaa team_id -> team_short_name
    team_id_to_name: dict[int, str] = {}
    for t in data.get("teams", []):
        team_id_to_name[t["id"]] = t.get("name", "")

    parhaat: list[tuple[int, dict]] = []  # (score, element)
    for el in elements:
        first = _normalize_name(el.get("first_name", ""))
        last = _normalize_name(el.get("second_name", ""))
        web = _normalize_name(el.get("web_name", ""))
        kokonimi = f"{first} {last}".strip()

        # Pisteytys: tarkka match korkein, alkupera/loppumaara seuraava, substring viimeinen
        score = 0
        if nimi_n == kokonimi or nimi_n == web or nimi_n == last or nimi_n == first:
            score = 100
        elif kokonimi.endswith(nimi_n) or kokonimi.startswith(nimi_n):
            score = 80
        elif nimi_n in kokonimi or nimi_n in web:
            score = 50
        elif nimi_n in last or last in nimi_n:
            score = 40

        if score > 0:
            # Boostaa jos joukkue match (jos annettu)
            if joukkue:
                team_n = _normalize_name(team_id_to_name.get(el.get("team", -1), ""))
                joukkue_n = _normalize_name(joukkue)
                if team_n == joukkue_n or team_n in joukkue_n or joukkue_n in team_n:
                    score += 30
            parhaat.append((score, el))

    if not parhaat:
        return None
    parhaat.sort(key=lambda x: x[0], reverse=True)
    paras = parhaat[0][1]
    photo = paras.get("photo", "")
    if not photo:
        return None
    pid = photo.replace(".jpg", "").replace(".png", "")
    return PHOTO_BASE.format(size=size, pid=pid)


def hae_pelaaja_kortti_html(nimi: str, joukkue: str | None = None,
                            xg: float | None = None,
                            stat_label: str = "xG") -> str:
    """Tuottaa HTML-kortin pelaajalle: kuva + nimi + (xG/maalit)."""
    kuva = hae_pelaajan_kuva(nimi, joukkue, size="110x140")
    if kuva:
        img_html = (
            f'<img src="{kuva}" style="height:90px;width:auto;border-radius:8px;'
            f'background:#1f2937;margin-bottom:6px" alt=""/>'
        )
    else:
        # Fallback: initiaalit
        initials = "".join(w[0] for w in str(nimi).split()[:2]).upper()
        img_html = (
            f'<div style="height:90px;width:90px;display:inline-flex;'
            f'align-items:center;justify-content:center;background:#374151;'
            f'color:white;border-radius:50%;font-weight:bold;font-size:24px;'
            f'margin-bottom:6px">{initials}</div>'
        )
    stat_html = ""
    if xg is not None:
        stat_html = (
            f'<div style="font-size:11px;opacity:0.8;color:#60a5fa">'
            f'{stat_label} <strong>{xg:.2f}</strong></div>'
        )
    return (
        f'<div style="text-align:center;padding:8px;background:rgba(255,255,255,0.04);'
        f'border-radius:10px;display:flex;flex-direction:column;align-items:center">'
        f'{img_html}'
        f'<div style="font-weight:600;font-size:12px;line-height:1.2;'
        f'margin-bottom:2px">{nimi}</div>'
        f'{stat_html}'
        f'</div>'
    )
