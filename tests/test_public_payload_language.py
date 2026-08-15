"""Julkinen payload on englanniksi (10.8.2026).

MIKSI TAMA ON OLEMASSA
Julkaisutarkistaja loysi etta englanninkielisen ilmaissivun caveat-rivi oli
SUOMEKSI livena: "Pre-season: pelaajabaselinet = edellisen kauden FPL-historia
...". Se tuli `meta.caveat`-kentasta. Mittaus paljasti ettei kyse ollut yhdesta
rivista: julkisessa payloadissa oli **seitseman** suomenkielista merkkijonoa
(method, caveat, promoted_prior_method, data_coverage.note, context_layer.note,
excluded_note, todo). Vain caveat renderoityi sivulle, mutta `/api/fantasy/xp`
on autentikoimaton eli kaikki seitseman olivat julkisia.

Yhden rivin korjaaminen olisi toistanut saman vian kuudella muulla pinnalla,
mika on tasan se vikaluokka joka osui 8.8. (SPA Fixtures/Table) ja uudelleen
10.8. (void-suodatin). Siksi portti on rivin sijaan saanto.

RAJAUS: skannataan vain `meta`, EI pelaajarivaja. Pelaajanimissa on
diakriitteja (Kadıoglu, Hojlund, Muller) ja niiden mukaanotto tuottaisi
valheita, jotka opettaisivat sivuuttamaan taman portin.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAYLOADS = [
    ROOT / "data" / "fpl_xp_projections.json",
    ROOT / "data" / "fpl_projections_phase0.json",
    ROOT / "data" / "spl_projections_phase0.json",
]

# Suomen tunnistin: skandit TAI yleisia sanoja jotka esiintyvat juuri naissa
# selitteissa. Sanalista on tarkeampi kuin skandit, koska "Pre-season:
# pelaajabaselinet ..." ei sisalla yhtaan a:ta tai o:ta.
#
# 15.8: sanalista paastikin lapi toisen vuodon. `data/fpl_manual_overrides.csv`
# -rivin vapaa note-teksti paatyy metaan (context_layer.applied_in_horizon) kun
# rivilla on attack/defence-kerroin, ja MM-vasymysrivin suomenkielinen perustelu
# ("keskitetty kuorma 1959 min josta 84 % puolustajilla ...") ei osunut yhteenkaan
# hakusanaan eika sisaltanyt aakkosia. Oppi: aihekohtainen sanalista vanhenee joka
# kerta kun uusi kentta alkaa kantaa vapaata tekstia -> lisatty RAKENNESANAT
# (josta/joka/vain/ilman/koska ...), jotka esiintyvat kaytannossa kaikessa
# suomenkielisessa proosassa aiheesta riippumatta.
FI_WORDS = re.compile(
    r"\b(pelaaja\w*|kausi|kauden|kaudet|kierro\w*|ennuste\w*|siirto\w*|"
    r"siirtoja|nousija\w*|joukkue\w*|luku|luvut|maalit|syotot|syötöt|"
    r"torjunn\w*|tarkentu\w*|arviolla|hintajarjestykse\w*|"
    r"hintajärjestykse\w*|saatavuus\w*|painon|otos|kentti\w*|"
    r"klientit|jattaa|jättää|avautuu|tunneta|nayta\w*|näy\w*|"
    # rakennesanat (aiheriippumattomat)
    r"josta|jossa|joka|jotka|jonka|joilla|jolla|jotta|vain|ilman|"
    r"koska|mutta|seka|sekä|kun|eika|eikä|jos|"
    # MM-vasymyskerrosten sanasto
    r"kuorma\w*|kuormit\w*|kaista\w*|keskitet\w*|puolustaj\w*|"
    r"hyokkay\w*|hyökkäy\w*|vasymy\w*|väsymy\w*|minuut\w*)\b",
    re.IGNORECASE)
FI_CHARS = re.compile(r"[äöÄÖ]")


def _strings(obj, path=""):
    """Kaikki merkkijonot meta-lohkosta polkuineen."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def _finnish_hits(text: str) -> list[str]:
    hits = FI_WORDS.findall(text)
    if FI_CHARS.search(text):
        hits = hits + ["skandi"]
    return hits


@pytest.mark.parametrize("payload", PAYLOADS, ids=lambda p: p.name)
def test_meta_on_englanniksi(payload: Path):
    if not payload.exists():
        pytest.skip(f"{payload.name} ei ole committattu")
    doc = json.loads(payload.read_text(encoding="utf-8"))
    meta = doc.get("meta") or {}
    assert meta, f"{payload.name}: meta-lohko puuttuu — portti olisi sokea"
    bad = []
    for path, text in _strings(meta):
        hits = _finnish_hits(text)
        if hits:
            bad.append(f"{path}: {sorted(set(hits))} :: {text[:110]}")
    assert not bad, (
        f"{payload.name}: julkisessa metassa on suomea, ja tama payload on "
        f"autentikoimaton:\n" + "\n".join(bad))


def test_tunnistin_ei_ole_sokea():
    """NEGATIIVINEN KONTROLLI. Ilman tata testi vihertaisi myos silloin kun
    regex on rikki, ja se olisi juuri se hiljainen vihrea jota vastaan tama
    tiedosto on kirjoitettu."""
    alkuperainen = ("Pre-season: pelaajabaselinet = edellisen kauden "
                    "FPL-historia, minuuttiarvio = kauden lopun rotaatio.")
    assert _finnish_hits(alkuperainen), "tunnistin ei nae alkuperaista vikaa"
    # 15.8: toinen mitattu vuoto — override-rivin note metan
    # context_layer.applied_in_horizon-listassa. Ei aakkosia, ei osumaa
    # alkuperaiseen sanalistaan; taman piti laueta ja se ei lauennut.
    override_note = ("GW1: override[wc_fatigue] Tottenham vs Brentford (A) "
                     "att x1.0 def x1.02 (keskitetty kuorma 1959 min josta "
                     "84 % puolustajilla)")
    assert _finnish_hits(override_note), "tunnistin ei nae 15.8 override-vuotoa"
    # Ja englanti ei saa laueta.
    englanti = ("Pre-season: player baselines come from last season's FPL "
                "history, and the minutes estimate comes from end-of-season "
                "rotation plus FPL availability.")
    assert not _finnish_hits(englanti), f"valhe: {_finnish_hits(englanti)}"
    # Myos englanniksi kirjoitettu override-note (sama rakenne kuin yllä) on
    # paastava lapi — muuten portti opettaa sivuuttamaan itsensa.
    englanti_note = ("GW1: override[wc_fatigue] Aston Villa vs Brighton (A) "
                     "att x1.0 def x1.03 (World Cup load 2188 min among "
                     "players over 300 tournament minutes; all of it "
                     "goalkeeper and defence)")
    assert not _finnish_hits(englanti_note), f"valhe: {_finnish_hits(englanti_note)}"
