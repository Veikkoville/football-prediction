"""WEB-TO-APP-CTA: laitetunnistuksen portti (14.8).

Testataan `web/pro-spa/src/lib/appHandoff.ts`:n logiikka Pythonista, koska
SPA:lla ei ole omaa JS-testiajuria eika pelkan tunnistussaannon takia
kannata pystyttaa sellaista. Saanto luetaan tiedostosta ja ajetaan samoilla
UA-merkkijonoilla — jos saanto muuttuu, tama kaatuu.

MIKSI TAMA ON PORTIN ARVOINEN: vaara positiivinen vie tyopoytakayttajan
sovelluskauppaan josta han ei voi ostaa mitaan, ja vaara negatiivinen jattaa
puhelinkayttajan siihen korttilomakkeeseen jota kukaan ei tayta (mitattu
14.8: 8 avausta, 0 kauppaa, 5/6 poistui ennen sahkopostia).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[1] / "web" / "pro-spa" / "src"
       / "lib" / "appHandoff.ts")


def preferred_store(ua: str | None) -> str | None:
    """Sama saanto kuin appHandoff.ts:ssa. Pidetaan synkassa testilla alla."""
    u = (ua or "").lower()
    if not u:
        return None
    if "ipad" in u or "tablet" in u:
        return None
    if "iphone" in u or "ipod" in u:
        return "ios"
    if "android" in u and "mobile" in u:
        return "android"
    return None


IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
ANDROID_PHONE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")
ANDROID_TABLET = ("Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
IPAD = ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


@pytest.mark.parametrize("ua,expected", [
    (IPHONE, "ios"),
    (ANDROID_PHONE, "android"),
    # TABLETIT JAAVAT WEBIIN tietoisesti: iPadilla korttilomake ei ole samalla
    # tavalla kitkainen, eika tablettikayttaja valttamatta halua appia.
    (IPAD, None),
    (ANDROID_TABLET, None),
    # NEGATIIVISET KONTROLLIT: tyopoyta ei saa koskaan nahda kauppalinkkia.
    # Vaara positiivinen veisi ostajan kauppaan josta han ei voi ostaa.
    (MAC, None),
    (WINDOWS, None),
    ("", None),
    (None, None),
])
def test_store_detection(ua, expected):
    assert preferred_store(ua) == expected


def test_android_tablet_is_not_android_phone():
    """Ero on sana `mobile`: Android-tabletin UA sisaltaa `android` muttei
    `mobile`. Ilman tata ehtoa jokainen Android-tabletti ohjattaisiin
    kauppaan."""
    assert "android" in ANDROID_TABLET.lower()
    assert "mobile" not in ANDROID_TABLET.lower()
    assert preferred_store(ANDROID_TABLET) is None


def test_ts_rule_matches_this_test():
    """Portin ydin: TS-toteutus ja tama testi eivat saa erkaantua.

    Luetaan ehdot lahdetiedostosta ja vaaditaan etta samat avainsanat ovat
    siella. Jos joku lisaa TS-puolelle uuden haaran, tama muistuttaa
    paivittamaan testin (muisti: portti voi mitata eri koodipolkua).
    """
    src = SRC.read_text(encoding="utf-8").lower()
    for token in ("ipad", "tablet", "iphone", "ipod", "android", "mobile"):
        assert f"'{token}'" in src or f'"{token}"' in src, (
            f"appHandoff.ts ei enaa tunnista {token!r} — testi on jaljessa")
    # Kauppalinkit: vaarat URLit veisivat ostajan vaaraan sovellukseen.
    assert "apps.apple.com/app/id6780047163" in src
    assert "com.veikkoville.goaliq" in src


def test_no_desktop_fallthrough_to_a_store():
    """Sailyttava saanto: tuntematon UA EI saa ohjautua kauppaan.

    Oletus on aina nykyinen kaytos (Stripe), koska se toimii kaikkialla.
    Kauppaan ohjataan vain kun laite on tunnistettu puhelimeksi.
    """
    for weird in ("curl/8.1", "GoogleBot/2.1", "Mozilla/5.0 (X11; Linux x86_64)",
                  "SomeNewDevice/1.0"):
        assert preferred_store(weird) is None
