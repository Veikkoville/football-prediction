"""Yksi URL-slug-kaava kaikille generaattoreille.

Miksi oma moduuli: kaava oli 5.8.2026 asti kirjoitettuna kahteen kertaan
(build_prediction_pages._slug ja build_fpl_page._pred_slug) sailla ainoana
suojana testi joka vertasi funktioita toisiinsa. Kun ottelusivujen kaava
korjattiin translitteroivaksi (#229-SEO / F2), fpl.html:n CS-solujen linkit
olisivat osoittaneet vanhaan muotoon eli 404:aan. Testi nappasi sen, mutta
oikea korjaus on poistaa kahdennus, ei paikata kopiota.

STDLIB-ONLY (kuten kutsujansa) -> ajettavissa CI:ssa ilman pipia.
"""

from __future__ import annotations

import re
import unicodedata

# NFKD hajottaa aksentin perusmerkiksi + yhdistyvaksi merkiksi, jolloin
# jalkimmainen voidaan pudottaa. Nama merkit EIVAT hajoa NFKD:lla — ne eivat
# ole aksentillisia perusmerkkeja vaan omia kirjaimiaan — joten esikaannos on
# pakollinen, ei varmuuden vuoksi -lisa. Ilman sita [^a-z0-9] soi merkin
# valiviivaksi: club-atl-tico-de-madrid-vs-m-laga-cf.
_TRANSLIT = {
    "ß": "ss", "ł": "l", "ø": "o", "đ": "d", "ð": "d", "þ": "th",
    "æ": "ae", "œ": "oe", "ı": "i", "ħ": "h", "ŋ": "ng",
}


def fold_ascii(s: str) -> str:
    """Aksentit pois, muu teksti ennallaan. Kayttokohde: llms.txt, joka on
    ASCII-konventiolla kirjoitettu ("Brasileirao Serie A")."""
    for src, dst in _TRANSLIT.items():
        s = s.replace(src, dst).replace(src.upper(), dst.upper())
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold_ascii(s.lower())).strip("-")
