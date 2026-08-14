"""Portit joukkuetason voimaohituksille.

Tama rivi liikuttaa JOKAISTA seuran pelaajaa kerralla, joten sen vaarin
meneminen on kalliimpaa kuin pelaajaohituksen. Painopiste on kolmessa
asiassa: merkkisopimus, vanhentumisportti ja hiljaisen epaonnistumisen
mahdottomuus.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path as _Path

import pytest

from src.models import fpl_team_overrides as tov


class FakeDC:
    def __init__(self):
        self.attack = {"Newcastle United": 0.20, "Arsenal": 0.40}
        self.defence = {"Newcastle United": -0.30, "Arsenal": -0.50}


def _write(tmp_path, body):
    p = tmp_path / "t.csv"
    p.write_text("team,attack_delta,defence_delta,reason,review_by\n" + body,
                 encoding="utf-8")
    return p


TODAY = _dt.date(2026, 8, 14)


# --------------------------------------------------------------------------
# Merkkisopimus — tama on se jonka voi saada vaarin
# --------------------------------------------------------------------------

def test_weakened_club_scores_less_and_concedes_more():
    """`defence[X]` on VASTUSTAJAN maaliodotuksessa, joten heikennys on
    attack NEGATIIVINEN ja defence POSITIIVINEN. Vaara merkki defencessa
    PARANTAISI juuri sita joukkuetta jota yritettiin heikentaa — ja se
    nayttaisi ulospain silta etta ohitus toimii."""
    dc = FakeDC()
    ovr = {"Newcastle United": {"attack": -0.10, "defence": 0.05,
                                "reason": "r", "review_by": "2026-10-05"}}
    tov.apply_team_overrides(dc, ovr)
    assert dc.attack["Newcastle United"] == pytest.approx(0.10)   # 0.20 - 0.10
    assert dc.defence["Newcastle United"] == pytest.approx(-0.25)  # -0.30 + 0.05
    # ...ja lambda liikkuu oikeaan suuntaan molemmilla puolilla:
    # oma hyokkays alas, vastustajan maaliodotus ylos.
    assert dc.attack["Newcastle United"] < 0.20
    assert dc.defence["Newcastle United"] > -0.30


def test_other_clubs_untouched():
    dc = FakeDC()
    tov.apply_team_overrides(dc, {"Newcastle United": {
        "attack": -0.10, "defence": 0.05, "reason": "", "review_by": "2026-10-05"}})
    assert dc.attack["Arsenal"] == 0.40 and dc.defence["Arsenal"] == -0.50


# --------------------------------------------------------------------------
# Vanhentumisportti — tiukempi kuin pelaajaohituksilla, ja syysta
# --------------------------------------------------------------------------

def test_expired_override_is_not_applied(tmp_path):
    """NEGATIIVINEN KONTROLLI. Reittaus korjaa itsensa kun 26/27-otteluita
    kertyy. Vanhentunut ohitus alkaisi taistella mallia vastaan tasan
    silloin kun mallilla on vihdoin oikeaa dataa."""
    p = _write(tmp_path, 'Newcastle United,-0.10,0.05,"x",2026-08-01\n')
    out, warn = tov.load_team_overrides(p, today=TODAY)
    assert out == {}
    assert any("MENNYT" in w for w in warn)


def test_valid_override_is_applied(tmp_path):
    """POSITIIVINEN KONTROLLI vanhentumisportille: ilman tata tyhja tulos
    voisi tarkoittaa joko 'vanhentunut' tai 'lukija on rikki'."""
    p = _write(tmp_path, 'Newcastle United,-0.10,0.05,"x",2026-10-05\n')
    out, warn = tov.load_team_overrides(p, today=TODAY)
    assert set(out) == {"Newcastle United"}
    assert warn == []


def test_missing_review_by_is_rejected(tmp_path):
    p = _write(tmp_path, 'Newcastle United,-0.10,0.05,"x",\n')
    out, warn = tov.load_team_overrides(p, today=TODAY)
    assert out == {} and any("review_by" in w for w in warn)


# --------------------------------------------------------------------------
# Rajat ja hiljaisen epäonnistumisen mahdottomuus
# --------------------------------------------------------------------------

def test_oversized_delta_is_rejected(tmp_path):
    """Kirjoitusvirhe (-1.0 eika -0.10) ei saa tuhota projektiota."""
    p = _write(tmp_path, 'Newcastle United,-1.0,0.05,"x",2026-10-05\n')
    out, warn = tov.load_team_overrides(p, today=TODAY)
    assert out == {} and any("delta" in w for w in warn)


def test_unknown_team_is_reported_not_silently_skipped():
    """Nimikirjoitusvirhe on todennakoisin tapa saada ohitus nayttamaan
    toimivalta tekematta mitaan. `found=False` pakottaa kutsujan huutamaan."""
    dc = FakeDC()
    applied = tov.apply_team_overrides(dc, {"Newcastle Utd": {
        "attack": -0.10, "defence": 0.05, "reason": "", "review_by": "2026-10-05"}})
    assert applied[0]["found"] is False
    assert dc.attack == FakeDC().attack


# --------------------------------------------------------------------------
# attack_mult — se sarake joka oikeasti tekee sen mita attack_delta ei tee
# --------------------------------------------------------------------------

def _write6(tmp_path, body):
    p = tmp_path / "t6.csv"
    p.write_text("team,attack_delta,defence_delta,reason,review_by,attack_mult\n"
                 + body, encoding="utf-8")
    return p


def test_attack_mult_defaults_to_one_on_old_five_column_rows(tmp_path):
    """Sarake lisattiin VIIMEISEKSI jotta vanhat rivit pysyvat toiminnassa.
    Jos joku siirtaa sen keskelle, reason ja review_by liukuvat sarakkeen
    verran ja rivi hylataan hiljaa."""
    p = _write6(tmp_path, 'Newcastle United,-0.10,0.05,"x",2026-10-05\n')
    out, warn = tov.load_team_overrides(p, today=TODAY)
    assert out["Newcastle United"]["attack_mult"] == 1.0 and warn == []


def test_attack_mult_is_loaded(tmp_path):
    p = _write6(tmp_path, 'Newcastle United,-0.10,0.05,"x",2026-10-05,0.85\n')
    out, _ = tov.load_team_overrides(p, today=TODAY)
    assert out["Newcastle United"]["attack_mult"] == 0.85


@pytest.mark.parametrize("bad", ["0.2", "1.9"])
def test_oversized_attack_mult_is_rejected(tmp_path, bad):
    """Tama kerroin liikuttaa seuran JOKAISTA pelaajaa, joten rajat ovat
    tiukemmat kuin pelaajatasolla."""
    p = _write6(tmp_path, f'Newcastle United,-0.10,0.05,"x",2026-10-05,{bad}\n')
    out, warn = tov.load_team_overrides(p, today=TODAY)
    assert out == {} and any("attack_mult" in w for w in warn)


def test_attack_mult_is_not_applied_to_the_rating(tmp_path):
    """attack_mult EI ole DC-suure. Jos se vuotaisi `dc.attack`iin, se
    laskisi lambdan JA pelaajien xg90:n eli tekisi saman asian kahdesti."""
    dc = FakeDC()
    tov.apply_team_overrides(dc, {"Newcastle United": {
        "attack": 0.0, "defence": 0.0, "attack_mult": 0.85,
        "reason": "", "review_by": "2026-10-05"}})
    assert dc.attack["Newcastle United"] == pytest.approx(0.20)
    assert dc.defence["Newcastle United"] == pytest.approx(-0.30)


def test_attack_mult_is_carried_to_the_caller(tmp_path):
    """Builderi tarvitsee kertoimen pelaajasilmukassa. Jos se ei kulje
    `applied`-listassa, builderi joutuisi lukemaan CSV:n uusiksi ja ne kaksi
    lukua voisivat erota."""
    dc = FakeDC()
    applied = tov.apply_team_overrides(dc, {"Newcastle United": {
        "attack": -0.10, "defence": 0.05, "attack_mult": 0.85,
        "reason": "", "review_by": "2026-10-05"}})
    assert applied[0]["attack_mult"] == 0.85


def test_the_override_never_reaches_the_graded_prediction_surface():
    """🔴 RAJAUSPORTTI (14.8). Repossa on nelja erillista Dixon-Coles-fittia
    ja tama ohitus kuuluu tasan yhteen.

    `/api/predict`-ennusteet logataan pre-match julkiseen track recordiin
    (accuracy_pipeline.py -> prediction_log.json -> accuracy.json). Jos
    kasisaato vuotaisi sinne, julkaistu osumatarkkuutemme mittaisi
    kasisaatoa eika mallia — eli tasan sen lupauksen jonka varaan tuote
    myydaan. Rajaus on helppo rikkoa vahingossa yhdella importilla, ja
    silloin mikaan ei huutaisi. Nyt huutaa tama.
    """
    root = _Path(__file__).resolve().parents[1]
    # Kolme FPL-pintaa saavat ohituksen (yhtenäistetty 14.8: aiemmin vain xP,
    # jolloin fixture-ticker näytti samasta seurasta eri luvun kuin xP).
    # `/api/predict` EI ole listalla eikä sinne saa lisätä.
    allowed = {"scripts/build_fpl_xp.py",
               "scripts/build_fpl_cs_fdr.py",
               "scripts/build_fpl_phase0.py"}
    offenders = []
    for f in list(root.glob("api/**/*.py")) + list(root.glob("scripts/**/*.py")) \
            + list(root.glob("src/**/*.py")):
        rel = f.relative_to(root).as_posix()
        if rel in allowed or rel.endswith("fpl_team_overrides.py"):
            continue
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        if any(k in src for k in ("load_team_overrides", "apply_team_overrides",
                                  "apply_to_fit")):
            offenders.append(rel)
    assert not offenders, (
        "joukkueohitus vuoti gradatulle tai muulle pinnalle: " + ", ".join(offenders)
        + " — ks. data/fpl_team_overrides.csv:n rajauslohko ennen kuin laajennat")


def test_missing_file_is_not_an_error(tmp_path):
    """Ohituksen puuttuminen ei saa KOSKAAN kaataa projektioajoa."""
    out, warn = tov.load_team_overrides(tmp_path / "ei-ole.csv", today=TODAY)
    assert out == {} and warn == []


def test_shipped_csv_is_valid_and_not_expired():
    """Repossa oleva rivi on OIKEASTI voimassa. Ilman tata portti voisi olla
    vihrea samalla kun tuotannon ohitus on hiljaa vanhentunut."""
    out, warn = tov.load_team_overrides()
    assert not any("delta" in w or "ISO" in w for w in warn), warn
    for team, o in out.items():
        assert abs(o["attack"]) <= tov.MAX_DELTA
        assert abs(o["defence"]) <= tov.MAX_DELTA
        assert o["reason"], f"{team}: perustelu puuttuu"
