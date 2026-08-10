"""Siirtovahdin portit (10.8.2026, Bruno G. -case).

Vahti on olemassa siksi etta builderin omat portit EIVAT voi nahda tata:
joukkue tulee samasta bootstrapista jonka builderi juuri haki, joten se ei voi
olla eri mielta itsensa kanssa. Ero syntyy ajan kuluessa, ja se mitataan
julkaistua artefaktia vasten.

Nama testit lukitsevat kolme asiaa:
  1. aito siirto loytyy,
  2. FPL:n ja mallin ERI NIMIKONVENTIO ei tuota valheita (negatiivinen
     kontrolli — ilman tata vahti huutaisi 207 kertaa ja aidot 2 hukkuisi),
  3. cachen TTL ei saa olla pidempi kuin refreshin vali, muuten paikallinen
     ajo voi leipoa vanhentuneen joukkueen artefaktiin.
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts.check_fpl_transfers import compare

ROOT = Path(__file__).resolve().parents[1]


def _boot(pairs: list[tuple[int, int]], teams: dict[int, str]) -> dict:
    return {
        "teams": [{"id": tid, "name": name} for tid, name in teams.items()],
        "elements": [{"id": pid, "team": tid} for pid, tid in pairs],
    }


def _doc(rows: list[tuple[int, str, str]]) -> dict:
    return {"players": [{"id": pid, "web_name": name, "team": team,
                         "owned_pct": 1.0, "xp_horizon_total": 10.0}
                        for pid, name, team in rows]}


def test_aito_siirto_loytyy():
    boot = _boot([(452, 1)], {1: "Arsenal", 4: "Newcastle"})
    doc = _doc([(452, "Bruno G.", "Newcastle United")])
    diffs = compare(doc, boot)
    assert len(diffs) == 1
    assert diffs[0]["ours"] == "Newcastle United"
    assert diffs[0]["fpl"] == "Arsenal"


def test_nimikonventio_ei_tuota_valhetta():
    """NEGATIIVINEN KONTROLLI. FPL sanoo "Man Utd" ja malli "Manchester
    United"; "Spurs" ja "Tottenham"; "Nott'm Forest" ja "Nottingham Forest".
    Naista yksikaan EI ole siirto."""
    teams = {1: "Man Utd", 2: "Spurs", 3: "Nott'm Forest", 4: "Man City"}
    boot = _boot([(1, 1), (2, 2), (3, 3), (4, 4)], teams)
    doc = _doc([(1, "B.Fernandes", "Manchester United"),
                (2, "Senesi", "Tottenham"),
                (3, "Sels", "Nottingham Forest"),
                (4, "Haaland", "Manchester City")])
    assert compare(doc, boot) == []


def test_pelaaja_pois_bootstrapista_raportoidaan():
    """Liigasta ulos myyty ei ole "ei eroa" vaan oma tapauksensa."""
    boot = _boot([(1, 1)], {1: "Arsenal"})
    doc = _doc([(1, "Rice", "Arsenal"), (999, "Myyty", "Arsenal")])
    diffs = compare(doc, boot)
    assert [d["id"] for d in diffs] == [999]
    assert diffs[0]["fpl"] is None


def test_bootstrap_cache_ei_saa_olla_refreshia_pidempi():
    """Bootstrapin TTL oli 6 h kun refresh ajaa 3 h valein. Paikallinen
    builderiajo saattoi siis leipoa jopa 6 h vanhan joukkuejaon artefaktiin.
    Lukitaan: TTL <= 1 h."""
    src = (ROOT / "src" / "data" / "fpl_api.py").read_text(encoding="utf-8")
    m = re.search(r"def fetch_bootstrap\(max_age_s: float = ([^,]+),", src)
    assert m, "fetch_bootstrapin allekirjoitus muuttui — tarkista TTL kasin"
    ttl = eval(m.group(1), {"__builtins__": {}}, {})  # noqa: S307
    assert ttl <= 3600, f"bootstrap-TTL {ttl}s on liian pitka siirtoikkunassa"


def test_vahtityokalu_on_workflowssa():
    """Ilman ajastusta vahti on kuollut koodi."""
    wf = ROOT / ".github" / "workflows" / "fpl-transfer-watch.yml"
    assert wf.exists(), "siirtovahdin workflow puuttuu"
    txt = wf.read_text(encoding="utf-8")
    assert "check_fpl_transfers.py" in txt
    assert "fpl-data-refresh" in txt, "vahti ei kaynnista refreshia"
