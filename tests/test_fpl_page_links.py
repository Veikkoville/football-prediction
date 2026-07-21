"""#152: fpl.html CS-solujen predict-linkit (mobiilin solu-tap-pariteetti).

Ei verkkoa, ei buildia — vain linkkilogiikka + slug-driftin vartija.
"""
from __future__ import annotations

from scripts.build_fpl_page import _pred_slug, predict_cell_href
from scripts.build_prediction_pages import _slug as pages_slug


def test_pred_slug_matches_prediction_pages_slug():
    # Ottelusivujen tiedostonimet syntyvät build_prediction_pages._slug:lla —
    # linkin pitää osua täsmälleen samaan slugiin tai solut 404:aavat.
    for name in ("Manchester United", "Nottingham Forest", "Brighton & Hove Albion",
                 "São Paulo", "Wolverhampton Wanderers", "Coventry"):
        assert _pred_slug(name) == pages_slug(name)


def test_predict_cell_href_falls_back_to_hub(tmp_path):
    # Ottelusivua ei ole generoitu → hub (on aina olemassa).
    assert predict_cell_href("Arsenal", "Coventry", "H", root=tmp_path) == "/predictions"


def test_predict_cell_href_uses_match_page_when_generated(tmp_path):
    d = tmp_path / "predictions" / "premier-league"
    d.mkdir(parents=True)
    (d / "arsenal-vs-coventry.html").write_text("x", encoding="utf-8")
    assert (predict_cell_href("Arsenal", "Coventry", "H", root=tmp_path)
            == "/predictions/premier-league/arsenal-vs-coventry.html")
    # Vieraspeli kääntää koti/vieras-järjestyksen → eri sivu, jota ei ole → hub.
    assert predict_cell_href("Arsenal", "Coventry", "A", root=tmp_path) == "/predictions"
