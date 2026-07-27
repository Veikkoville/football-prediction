"""Classic-favikonit goaliq.app:lle: tumma pohja + antiikva IQ.

TAUSTA (27.7): sivuston favikoni oli yhä vanha magenta-gradientti-badge —
sama aikakausi kuin sovellusikoni, eri kuin muu classic-ilme.

MIKSI TUMMA POHJA EIKÄ CREAM: selaimen välilehti on vaalea useimmilla
käyttäjillä, ja 26.7. avatar-vertailu mittasi että cream-variantti katoaa
vaaleaan taustaan pienessä koossa. Tumma ink erottuu MOLEMMILLA teemoilla.
Villen some-avatar on cream (hänen valintansa, eri konteksti) — tässä
konteksti on juuri se jossa cream ei toimi.

MIKSI NELIÖ EIKÄ YMPYRÄ apple-touch-ikonissa: iOS pyöristää sen itse.
Ympyrä pyöristyisi kahdesti ja näyttäisi pieneltä laatikkonsa sisällä.

Kirjainmuoto identtinen avatarin ja wordmarkin kanssa: Cormorant Garamond,
"I" vaalea + "Q" magenta.

Ajo:
  .venv/Scripts/python.exe assets/brand/gen_classic_favicon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
# Fontti asuu mobiili-reposssa; classic-assetit generoidaan sieltä.
CG = ROOT.parent / "goaliq-app" / "fonts" / "CormorantGaramond-var.ttf"

INK = (0x20, 0x1F, 0x1D, 255)
CREAM = (0xF3, 0xF2, 0xF2, 255)
MAGENTA = (0xFF, 0x2E, 0x7E, 255)

# Renderöidään isona ja skaalataan alas → terävät reunat pienissä koissa.
SUPER = 1024


def _font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(CG), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def render_square(size: int, ring: bool = True) -> Image.Image:
    """Täysleveä ink-neliö + keskitetty IQ.

    KAKSI KORJAUSTA ensimmäisen vedoksen jälkeen, molemmat mitattu
    välilehtikoossa (_favicon-vertailu.png):

    1. Kirjainkoko 0.46 -> 0.62. Antiikva ohenee pienessä koossa, ja 16 px:n
       favikonissa 0.46 jätti kirjainparille ~7 px per kirjain — tunnistamaton
       täplä. Favikoni on brändin PIENIN pinta, joten se kestää vähiten
       hienovaraisuutta.
    2. Cream-reunus. Ink-pohja sulautui tumman selainteeman kromiin, jolloin
       ikonilta katosi raja ja se näytti irrallisilta kirjaimilta. Reunus antaa
       muodon molemmilla teemoilla. Sama syy miksi avatar-A-inkissä on ohut
       rengas.
    """
    img = Image.new("RGBA", (SUPER, SUPER), INK)
    d = ImageDraw.Draw(img)
    if ring:
        w = int(SUPER * 0.045)
        d.rectangle(
            [w // 2, w // 2, SUPER - w // 2, SUPER - w // 2],
            outline=(CREAM[0], CREAM[1], CREAM[2], 90),
            width=w,
        )
    f = _font(int(SUPER * 0.62))
    l, t, r, b = d.textbbox((0, 0), "IQ", font=f)
    x0 = SUPER / 2 - (r - l) / 2
    y = SUPER / 2 - (t + b) / 2
    d.text((x0 - l, y), "I", font=f, fill=CREAM)
    iw = d.textlength("I", font=f)
    d.text((x0 + iw - l, y), "Q", font=f, fill=MAGENTA)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = HERE
    for name, size in (
        ("goaliq-favicon-32.png", 32),
        ("goaliq-favicon-48.png", 48),
        ("goaliq-apple-touch-180.png", 180),
    ):
        render_square(size).save(out / name)
        print(f"[ok] {name}")

    # favicon.ico juureen — monikokoinen, selaimet valitsevat sopivan.
    ico = ROOT / "favicon.ico"
    base = render_square(256)
    base.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print(f"[ok] {ico.name} (16/32/48/64)")

    # Katselmointiarkki: miltä se näyttää välilehtikoossa molemmilla taustoilla.
    sheet = Image.new("RGBA", (420, 150), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.rectangle([210, 0, 420, 150], fill=(0x1E, 0x1E, 0x1E, 255))
    lf = ImageFont.truetype(str(CG), 18)
    d.text((16, 12), "vaalea valilehti", font=lf, fill=(0x20, 0x1F, 0x1D, 255))
    d.text((226, 12), "tumma valilehti", font=lf, fill=(0xF3, 0xF2, 0xF2, 255))
    for i, s in enumerate((16, 24, 32, 48)):
        icon = render_square(s)
        x = 20 + i * 46
        sheet.alpha_composite(icon, (x, 70 + (48 - s) // 2))
        sheet.alpha_composite(icon, (x + 210, 70 + (48 - s) // 2))
    sheet.save(out / "_favicon-vertailu.png")
    print("[ok] _favicon-vertailu.png")


if __name__ == "__main__":
    main()
