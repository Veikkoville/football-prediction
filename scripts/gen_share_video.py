# -*- coding: utf-8 -*-
"""GoalIQ-jakovideo: pystymuotoinen klippi TikTokiin, Reelsiin ja Shortsiin.

TAUSTA (9.8.2026): staattinen kortti toimii Redditissa, X:ssa, Blueskyssa ja
IG-feedissa, mutta TikTok ja Reels ovat videoformaatteja eika kuva liiku
niissa lainkaan. Video oli ainoa asset jota emme generoineet, joten se oli
myos ainoa syy jattaa kaksi kanavaa kayttamatta.

Sama DATA kuin kortissa: taman skriptin builderit tuodaan suoraan
gen_share_card.py:sta, joten kortti ja video eivat voi kertoa eri lukuja.
Jos lisaat uuden korttityypin, se on automaattisesti myos videona.

FORMAATTI 1080x1920 (9:16). Kortti on 1080x1350 (4:5), joten layout on
kirjoitettu erikseen — mutta paletti, fontit ja wordmark tulevat kortista,
jotta ilme on sama.

AANI: renderoidaan HILJAISENA tarkoituksella. TikTokin ja Reelsin oma
aanikirjasto on lisensoitu; mukaan paketoitu musiikki ei olisi. Lisaa aani
sovelluksessa julkaisun yhteydessa.

FFMPEG tulee imageio-ffmpeg-paketista joka on jo riippuvuuksissa; erillista
asennusta ei tarvita.

KAYTTO
  python -m scripts.gen_share_video value --top 10
  python -m scripts.gen_share_video xp --top 8 --seconds 12
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.gen_share_card import (  # noqa: E402
    AMBER, BUILDERS, CREAM, FONT_BOLD, FONT_MED, GW_CAPABLE, INK, INK2,
    LINE, MUTED, OUT_DIR, TAG_LINE, WORDMARK, _font, _shrink,
)

# --- Pystylayout (9:16). Mitat isompia kuin kortissa: video katsotaan
# puhelimessa peukalon etaisyydelta ja usein ilman aania, joten rivin on
# oltava luettava ilman zoomausta.
VW, VH, VMX = 1080, 1920, 70
V_ROW_TOP, V_ROW_H = 620, 108
V_FOOT_Y = VH - 130          # alatunniste ankkuroitu ALAREUNAAN, ei riveihin:
FPS = 30                     # muuten se liikkuu rivimaaran mukana ja leikkautui
                             # ensimmaisessa renderissa amber-palkin alle (9.8)


def _base(spec: dict, n_rows: int) -> Image.Image:
    """Kaikki paitsi rivit: tausta, wordmark, otsikot, sarakeotsikot, alatunniste."""
    im = Image.new("RGB", (VW, VH), INK)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, VW, 300], fill=INK2)

    if WORDMARK.exists():
        wm = Image.open(WORDMARK).convert("RGBA")
        scale = 420 / wm.width
        wm = wm.resize((420, int(wm.height * scale)), Image.LANCZOS)
        im.paste(wm, ((VW - wm.width) // 2, 92), wm)

    d.rectangle([(VW - 150) // 2, 236, (VW + 150) // 2, 244], fill=AMBER)

    f_title = _shrink(d, spec["title"], 76, VW - 2 * VMX, 44, FONT_BOLD)
    tw = d.textlength(spec["title"], font=f_title)
    d.text(((VW - tw) / 2, 380), spec["title"], font=f_title, fill=CREAM)

    f_sub = _font(FONT_MED, 30)
    sw = d.textlength(spec["subtitle"], font=f_sub)
    d.text(((VW - sw) / 2, 494), spec["subtitle"], font=f_sub, fill=MUTED)

    f_col = _font(FONT_MED, 24)
    d.text((VMX, V_ROW_TOP - 44), spec["nameLabel"], font=f_col, fill=MUTED)
    d.text((VW - VMX - d.textlength(spec["valueLabel"], font=f_col),
            V_ROW_TOP - 44), spec["valueLabel"], font=f_col, fill=MUTED)

    # Rivit eivat saa valua alatunnisteen paalle. Hiljainen paallekkaisyys
    # olisi juuri se vikaluokka jota ei huomaa ennen kuin video on julkaistu,
    # joten se kaadetaan tassa.
    rows_bottom = V_ROW_TOP + n_rows * V_ROW_H
    if rows_bottom > V_FOOT_Y - 20:
        raise SystemExit(
            f"Liikaa rivejä pystyvideoon: {n_rows} riviä paattyy y={rows_bottom}, "
            f"alatunniste alkaa y={V_FOOT_Y}. Kayta --top {int((V_FOOT_Y - 20 - V_ROW_TOP) // V_ROW_H)} "
            "tai pienempaa.")

    f_foot = _font(FONT_MED, 24)
    for i, key in enumerate(("footNote", "footNote2")):
        if spec.get(key):
            d.text((VMX, V_FOOT_Y + i * 36), spec[key], font=f_foot, fill=MUTED)
    handle = "@goaliqapp"
    d.text((VW - VMX - d.textlength(handle, font=f_foot), V_FOOT_Y),
           handle, font=f_foot, fill=AMBER)
    d.rectangle([0, VH - 10, VW, VH], fill=AMBER)
    return im


def _draw_row(d: ImageDraw.ImageDraw, r: dict, y: float, first: bool) -> None:
    cy = y + V_ROW_H / 2
    d.rectangle([VMX - 14, y + 5, VW - (VMX - 14), y + V_ROW_H - 5],
                outline=AMBER if first else LINE, width=3 if first else 1)

    f_rank = _font(FONT_BOLD, 38)
    rk = str(r["rank"])
    d.text((VMX + 40 - d.textlength(rk, font=f_rank), cy - 22), rk,
           font=f_rank, fill=AMBER if first else MUTED)

    x = VMX + 92
    f_name = _shrink(d, r["name"], 44, 430, 26, FONT_BOLD)
    d.text((x, cy - f_name.size * 0.62), r["name"], font=f_name, fill=CREAM)
    x += d.textlength(r["name"], font=f_name) + 18

    f_tag = _font(FONT_BOLD, 22)
    if r.get("tag"):
        pw = d.textlength(r["tag"], font=f_tag) + 20
        d.rectangle([x, cy - 20, x + pw, cy + 20], outline=TAG_LINE, width=1)
        d.text((x + 10, cy - 13), r["tag"], font=f_tag, fill=CREAM)
        x += pw + 14

    if r.get("team"):
        f_team = _font(FONT_MED, 26)
        d.text((x, cy - 13), r["team"], font=f_team, fill=MUTED)

    f_val = _font(FONT_BOLD, 48)
    vw_ = d.textlength(r["value"], font=f_val)
    d.text((VW - VMX - vw_, cy - 28), r["value"], font=f_val,
           fill=AMBER if first else CREAM)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit(
            "ffmpeg puuttuu. Se tulee imageio-ffmpeg-paketista: "
            "pip install imageio-ffmpeg")


def render_video(spec: dict, out_path: Path, seconds: float) -> Path:
    rows = spec["rows"]
    n = len(rows)
    base = _base(spec, n)

    # Ajoitus: intro pitaa otsikon nakyvissa, rivit ilmestyvat tasavalein,
    # outro jattaa koko listan ruudulle luettavaksi. Outro on pisin osa
    # tarkoituksella — katsoja pysayttaa videon lukeakseen listan.
    intro, outro = 0.9, 2.6
    reveal_total = max(seconds - intro - outro, n * 0.25)
    per_row = reveal_total / n
    total_frames = int(round(seconds * FPS))

    tmp = Path(tempfile.mkdtemp(prefix="giq_vid_"))
    try:
        for f in range(total_frames):
            t = f / FPS
            im = base.copy()
            d = ImageDraw.Draw(im)
            for i, r in enumerate(rows):
                start = intro + i * per_row
                if t < start:
                    break
                # 0.28 s sisaanajo: liukuu ylos ja kirkastuu.
                p = min((t - start) / 0.28, 1.0)
                y = V_ROW_TOP + i * V_ROW_H + (1 - p) * 26
                if p >= 1.0:
                    _draw_row(d, r, y, i == 0)
                else:
                    layer = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
                    _draw_row(ImageDraw.Draw(layer), r, y, i == 0)
                    a = layer.split()[3].point(lambda v: int(v * p))
                    layer.putalpha(a)
                    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
                    d = ImageDraw.Draw(im)
            im.save(tmp / f"f{f:05d}.png")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [_ffmpeg(), "-y", "-framerate", str(FPS),
               "-i", str(tmp / "f%05d.png"),
               "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-crf", "18",
               "-movflags", "+faststart", str(out_path)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"ffmpeg epaonnistui:\n{p.stderr[-1500:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="GoalIQ share video (9:16)")
    ap.add_argument("card", choices=sorted(BUILDERS))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--seconds", type=float, default=11.0)
    ap.add_argument("--from-gw", type=int, default=1)
    ap.add_argument("--to-gw", type=int, default=6)
    ap.add_argument("--metric", choices=("avg", "total"), default="avg")
    ap.add_argument("--sort", default="pts")
    ap.add_argument("--min-mins", type=int, default=400)
    a = ap.parse_args()

    if a.card not in GW_CAPABLE and (a.from_gw != 1 or a.to_gw != 6):
        print(f"HUOM: {a.card} ei tue GW-ikkunaa, argumentit ohitetaan.",
              file=sys.stderr)

    spec = BUILDERS[a.card](a)
    spec["rows"] = spec["rows"][:a.top]
    out = OUT_DIR / (Path(spec["file"]).stem + "_9x16.mp4")
    render_video(spec, out, a.seconds)
    mb = out.stat().st_size / 1e6
    print(f"{spec['title']} ({len(spec['rows'])} rivia, {a.seconds:.0f} s, "
          f"{mb:.1f} MB) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
