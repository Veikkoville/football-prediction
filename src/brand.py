"""GoalIQ-brändimerkki yhdestä lähteestä (1.8.2026, Villen päätös).

Tausta: merkkiä oli kolmea eri versiota. `fpl.html` käytti amber-laatikkoa +
ink-IQ:ta (= markkinointi-ilmeen merkki), etusivu käytti outline-neliötä jossa
Q oli MAGENTA, ja longtail-/ennustesivuilla ei ollut merkkiä lainkaan — vain
teksti "GoalIQ". Ville: logo on kaikilla sivuilla sama, ja se on se keltaisella
pohjalla oleva IQ.

Magenta poistettiin samalla koko paletista, joten merkissä on enää kaksi väriä:
amber-täyttö ja ink-teksti.

Käyttö generaattoreissa: `from src.brand import logo_svg, brand_link`.
"""
from __future__ import annotations

AMBER = "#F5C542"
INK = "#0B0A09"
MONO = "IBM Plex Mono,ui-monospace,Consolas,monospace"


def logo_svg(size: int = 26, cls: str = "brand-icon") -> str:
    """Amber-laatikko + ink-IQ. viewBox on aina 44 — koko tulee width/heightista,
    jotta sama merkki skaalautuu headeriin ja jalkaan ilman eri tiedostoja."""
    return (
        f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 44 44" '
        f'role="img" aria-label="GoalIQ" focusable="false">'
        f'<rect x="0" y="0" width="44" height="44" fill="{AMBER}"/>'
        f'<text x="22" y="30" text-anchor="middle" font-family="{MONO}" '
        f'font-size="20" font-weight="700" letter-spacing="-0.5" fill="{INK}">IQ</text>'
        f"</svg>"
    )


def brand_link(href: str = "/", size: int = 26, cls: str = "brand") -> str:
    """Merkki + sanamerkki yhtenä linkkinä — sama rakenne joka sivulla."""
    return (
        f'<a class="{cls}" href="{href}">{logo_svg(size)}'
        f"Goal<span>IQ</span></a>"
    )
