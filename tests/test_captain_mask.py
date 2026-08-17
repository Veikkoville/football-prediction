"""Portti: kapteenirankkeri on premium, yksi valinta on ilmainen.

TAUSTA (15.8.2026, Villen paatos). Mittasin tuotannosta autentikoimattomana:
`/api/fantasy/captain` palautti `top3` JA `differential` ilman maskausta, eli
tasan sen mita premium-paneeli myy ("Captain ranker: top three, a differential
pick and bonus expectation"). Portti oli VAIN selaimessa — RateTeam.svelte
piilotti sen `premium=false`-propilla — joten suora API-kutsu sai koko
ominaisuuden.

Raja on nyt tasmalleen se mita myyntisivu jo lupaa:
    FREE     "Rate my team, with a captain pick"        -> 1 pick
    PREMIUM  "Captain ranker: top three, a differential" -> 3 + differential
Copya ei tarvinnut muuttaa, koska koodi siirtyi vastaamaan copya eika toisin
pain.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.premium import FREE_CAPTAIN_PICKS, mask_captain_payload  # noqa: E402


def _payload():
    return {
        "meta": {"gw": 1},
        "top3": [
            {"id": 1, "web_name": "A", "gw_xp": 6.1, "e_bonus": 0.8},
            {"id": 2, "web_name": "B", "gw_xp": 5.9},
            {"id": 3, "web_name": "C", "gw_xp": 5.2},
        ],
        "differential": {"id": 9, "web_name": "Diff", "gw_xp": 4.8},
    }


def test_free_saa_yhden_valinnan():
    out = mask_captain_payload(_payload())
    assert len(out["top3"]) == FREE_CAPTAIN_PICKS == 1
    assert out["top3"][0]["web_name"] == "A", "maski ei sailyttanyt parasta"


def test_differential_poistetaan_kokonaan():
    """Se on nimenomaan myyty premium-riville, joten sita ei typisteta vaan
    poistetaan. Typistetty differential olisi yha differential."""
    out = mask_captain_payload(_payload())
    assert out["differential"] is None


def test_maski_kerrotaan_metassa():
    """Klientti tarvitsee tiedon nayttaakseen lukon eika tyhjaa kohtaa."""
    m = mask_captain_payload(_payload())["meta"]
    assert m["masked"] is True
    assert "differential" in m["mask"]


def test_rivin_sisalto_sailyy():
    """Maski koskee rivien MAARAA, ei niiden sisaltoa: enrichment
    (e_bonus, set_pieces) ajetaan ennen maskausta, joten free-rivi on yhta
    rikas kuin premium-rivi."""
    out = mask_captain_payload(_payload())
    assert out["top3"][0]["e_bonus"] == 0.8


def test_alkuperaista_payloadia_ei_mutatoida():
    """Maski palauttaa kopion. Mutatointi vuotaisi cachen kautta premiumille."""
    p = _payload()
    mask_captain_payload(p)
    assert len(p["top3"]) == 3
    assert p["differential"] is not None


def test_endpoint_kutsuu_maskia():
    """Funktio yksin ei riita: 15.8:n vika oli ETTA SITA EI KUTSUTTU."""
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    # Etsi dekoraattorin ALKU, ei koko rivia: 17.8. reiteille lisattiin
    # `description=`-parametri samalle riville (openapi.json:n suomivuoto), ja
    # tasmalleen-rivi-vertailu hajosi siita vaikka maski oli tallella.
    i = src.index('@app.get("/api/fantasy/captain"')
    j = src.index('@app.get("/api/fantasy/differentials"', i)
    lohko = src[i:j]
    assert "mask_captain_payload" in lohko, "endpoint ei maskaa"
    assert "is_premium_request" in lohko, "endpoint ei tarkista premiumia"
