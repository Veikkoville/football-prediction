# -*- coding: utf-8 -*-
"""IG Reels -video (9:16, 1080x1920) GoalIQ:n korttien ilmeella.

MIKSI TAMA ON TASSA TIEDOSTOSSA
Jakokortin renderoija (gen_share_card.py) on jo taalla, ja 9.8. paatettiin
etta Python-puolella on YKSI toteutus per layout. Video kayttaa tismalleen
samaa palettia, fonttia ja wordmarkia importtaamalla ne siita -> jos brandi
muuttuu, video ei jaa jalkeen omana kopiona.

LUVUT EIVAT OLE KOODISSA. Ne luetaan committatusta artefaktista samalla
suodattimella jota copy lupaa, joten video ei voi vaittaa eri asiaa kuin sivu.

KORTIT
  cs     (oletus) clean sheet -todennakoisyys. Tama on charterin ykkoskiila:
         "FPL nayttaa FDR:n numerona, me nayttaa mika puolustus pitaa nollan".
  value  xP per miljoona. EI OLETUS kahdesta syysta: kulma postattiin 9.8.
         Redditissa, ja lista nostaa karkeen pelaajan jota Villen 10.8. ohje
         kieltaa kayttamasta markkinoinnissa. Sailytetty koska mekaniikka on
         sama ja kulma palaa kayttoon kun lista muuttuu.

AANIRAITA: mykka AAC. Instagram kohtelee taysin aanetonta tiedostoa
epaluotettavasti (osa clienteista hylkaa), joten raita on olemassa mutta tyhja.

KAYTTO
    python scripts/gen_reel.py                    # cs-kortti, 15 s
    python scripts/gen_reel.py --card value
    python scripts/gen_reel.py --out polku.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.gen_share_card import (  # noqa: E402
    AMBER, CREAM, FONT_BOLD, FONT_MED, INK, MUTED, WORDMARK,
)

W, H = 1080, 1920
FPS = 30
XP = ROOT / "data" / "fpl_xp_projections.json"
PHASE0 = ROOT / "data" / "fpl_projections_phase0.json"
STARTER_MINS = 60.0          # sama raja kuin copyn "expected starters only"
N_ROWS = 5
HORIZON = 6

# Ylareuna 0-250 px ja alareuna 1520-1920 px ovat Instagramin oman UI:n alla
# (kayttajanimi, caption, napit). Kaikki sisalto pidetaan valissa, ja se on
# mitattu pikseleista eika arvattu.
SAFE_TOP, SAFE_BOTTOM = 250, 1520


# ---------------------------------------------------------------- kortit
def card_cs() -> dict:
    doc = json.loads(PHASE0.read_text(encoding="utf-8"))
    teams = doc.get("teams") or []
    if not teams:
        raise SystemExit("VIRHE: phase0-artefaktissa 0 joukkuetta.")
    rows, avgs = [], {}
    for t in teams:
        fx = t.get("fixtures") or []
        if not fx:
            continue
        six = fx[:HORIZON]
        avgs[t["name"]] = sum(f["cs_pct"] for f in six) / len(six)
        g1 = fx[0]
        rows.append({
            "name": t["name"],
            "meta": f"{'vs' if g1['venue'] == 'H' else 'at'} "
                    f"{g1['opponent']}",
            "sort": g1["cs_pct"],
            "val": f"{round(g1['cs_pct'])}%",
        })
    rows.sort(key=lambda r: -r["sort"])
    top = rows[:N_ROWS]
    best_six = max(avgs.items(), key=lambda kv: kv[1])
    if best_six[0] != top[0]["name"]:
        # Jos GW1-karki ja kuuden kierroksen karki eroavat, kolmannen ruudun
        # vaite on eri. Kaadetaan mieluummin kuin kirjoitetaan vaarin.
        raise SystemExit(
            f"VIRHE: GW1-karki on {top[0]['name']} mutta kuuden kierroksen "
            f"karki {best_six[0]} — kolmannen ruudun copy pitaa kirjoittaa "
            f"uudelleen kasin.")
    return {
        # Lyhenne on tahallinen: lyhenteiden puute on yksittaisista selkein
        # AI-tunnusmerkki (AI-TELL-CHECKLIST kohta C).
        "hook": "FPL tells you a fixture is easy. It doesn’t tell you who "
                "keeps the clean sheet.",
        "title": "CLEAN SHEET CHANCE",
        "sub1": "Gameweek 1",
        "sub2": "Our match model, not a difficulty rating",
        "rows": top,
        "point": f"{best_six[0]} stay top across the first six as well.",
        "point2": f"{round(best_six[1])}% a game.",
        "cta1": "The full table is free",
        "cta2": "Every team, every gameweek",
        "generated": (doc.get("meta") or {}).get("generated_at"),
    }


def card_value() -> dict:
    doc = json.loads(XP.read_text(encoding="utf-8"))
    starters = [p for p in doc["players"]
                if p.get("xmins", 0) >= STARTER_MINS and p.get("price")
                and p.get("status") == "a"]
    if len(starters) < N_ROWS:
        raise SystemExit("VIRHE: liian vahan status 'a' -avaajia.")
    top = sorted(starters,
                 key=lambda p: -(p["xp_horizon_total"] / p["price"]))[:N_ROWS]
    return {
        "hook": "Your fourth defender is the cheapest points on the board.",
        "title": "POINTS PER MILLION",
        "sub1": "First six gameweeks",
        "sub2": "Expected starters only",
        "rows": [{"name": p["web_name"],
                  "meta": f"{p['team_short']}   {p['price']:.1f}m",
                  "val": f"{p['xp_horizon_total'] / p['price']:.2f}"}
                 for p in top],
        "point": "Every one of them is expected to start.",
        "point2": "That is the whole trick.",
        "cta1": "The full list is free",
        "cta2": "No account, no sign-in",
        "generated": (doc.get("meta") or {}).get("generated_at"),
    }


CARDS = {"cs": card_cs, "value": card_value}


def check_glyphs(text: str) -> None:
    """Puuttuva glyfi piirtyy tyhjana laatikkona eika kaada mitaan, joten se
    tarkistetaan erikseen (esim. Kadıoglu, Nott'm Forest -apostrofi)."""
    f = ImageFont.truetype(str(FONT_BOLD), 40)
    empty = f.getmask("").getbbox()
    for ch in set(text):
        if ch.isspace():
            continue
        if f.getmask(ch).getbbox() == empty and empty is not None:
            raise SystemExit(f"VIRHE: fontista puuttuu merkki {ch!r}")


# ---------------------------------------------------------------- piirto
def _f(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if d.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _base() -> Image.Image:
    return Image.new("RGB", (W, H), INK)


def _wordmark(img: Image.Image, y: int, width: int = 420) -> None:
    if not WORDMARK.exists():
        return
    wm = Image.open(WORDMARK).convert("RGBA")
    h = round(wm.height * width / wm.width)
    wm = wm.resize((width, h), Image.LANCZOS)
    img.paste(wm, ((W - width) // 2, y), wm)


def frame_hook(t: float, spec: dict) -> Image.Image:
    img = _base()
    d = ImageDraw.Draw(img)
    f = _f(FONT_BOLD, 88)
    lines = _wrap(d, spec["hook"], f, W - 160)
    y = H // 2 - (len(lines) * 108) // 2 - 60
    for ln in lines:
        d.text((80, y), ln, font=f, fill=CREAM)
        y += 108
    grow = max(0.0, min(1.0, (t - 0.35) / 0.9))
    if grow > 0:
        d.rectangle([80, y + 30, 80 + int((W - 160) * grow), y + 44],
                    fill=AMBER)
    return img


def frame_table(t: float, spec: dict) -> Image.Image:
    img = _base()
    d = ImageDraw.Draw(img)
    d.text((80, 300), spec["title"], font=_f(FONT_BOLD, 74), fill=AMBER)
    d.text((80, 392), spec["sub1"], font=_f(FONT_MED, 40), fill=CREAM)
    d.text((80, 448), spec["sub2"], font=_f(FONT_MED, 34), fill=MUTED)

    top, row_h = 610, 180
    f_meta = _f(FONT_MED, 36)
    f_val, f_rank = _f(FONT_BOLD, 72), _f(FONT_BOLD, 44)
    for i, r in enumerate(spec["rows"]):
        if t < 0.45 + i * 0.85:
            break
        y = top + i * row_h
        val = r["val"]
        val_w = d.textlength(val, font=f_val)
        f_name = _f(FONT_BOLD, 64)
        # Nimi ei saa ajaa arvon alle. Kutistetaan nimi eika arvoa: arvo on
        # se mita kuvassa tullaan lukemaan.
        while d.textlength(r["name"], font=f_name) > W - 250 - val_w - 40:
            f_name = _f(FONT_BOLD, f_name.size - 2)
        d.text((80, y + 26), str(i + 1), font=f_rank, fill=MUTED)
        d.text((170, y), r["name"], font=f_name, fill=CREAM)
        d.text((170, y + 76), r["meta"], font=f_meta, fill=MUTED)
        d.text((W - 80 - val_w, y + 18), val, font=f_val,
               fill=AMBER if i == 0 else CREAM)
        d.line([80, y + row_h - 26, W - 80, y + row_h - 26],
               fill=(60, 58, 54), width=2)
    return img


def frame_point(t: float, spec: dict) -> Image.Image:
    img = _base()
    d = ImageDraw.Draw(img)
    f = _f(FONT_BOLD, 86)
    lines = _wrap(d, spec["point"], f, W - 160)
    y = H // 2 - (len(lines) * 106) // 2 - 40
    for ln in lines:
        d.text((80, y), ln, font=f, fill=CREAM)
        y += 106
    if t > 10.4:
        f2 = _f(FONT_MED, 52)
        d.text((80, y + 40), spec["point2"], font=f2, fill=AMBER)
    return img


def frame_end(t: float, spec: dict) -> Image.Image:
    img = _base()
    d = ImageDraw.Draw(img)
    _wordmark(img, 620)
    f = _f(FONT_BOLD, 70)
    d.text(((W - d.textlength(spec["cta1"], font=f)) / 2, 900), spec["cta1"],
           font=f, fill=CREAM)
    f2 = _f(FONT_MED, 44)
    d.text(((W - d.textlength(spec["cta2"], font=f2)) / 2, 1000), spec["cta2"],
           font=f2, fill=MUTED)
    if t > 13.0:
        f3 = _f(FONT_BOLD, 56)
        d.text(((W - d.textlength("goaliq.app", font=f3)) / 2, 1130),
               "goaliq.app", font=f3, fill=AMBER)
    return img


def build_frame(t: float, spec: dict) -> Image.Image:
    if t < 2.6:
        return frame_hook(t, spec)
    if t < 9.4:
        return frame_table(t, spec)
    if t < 12.2:
        return frame_point(t, spec)
    return frame_end(t, spec)


def check_safe_areas(spec: dict) -> None:
    """IG:n UI peittaa ylimmat ~250 ja alimmat ~400 px. Mitataan pikseleista
    joka ruudusta, ei luoteta layoutin lukemiseen."""
    import numpy as np
    bg = np.asarray(Image.new("RGB", (8, 8), INK)).max()
    for t in (1.6, 9.0, 11.0, 14.5):
        a = np.asarray(build_frame(t, spec))
        if a[:SAFE_TOP].max() > bg or a[SAFE_BOTTOM:].max() > bg:
            raise SystemExit(
                f"VIRHE: sisaltoa IG:n UI:n alla ruudussa t={t}s")


# ---------------------------------------------------------------- enkoodaus
def encode(out: Path, spec: dict, seconds: float = 15.0) -> Path:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "pipe:0",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    try:
        for i in range(int(seconds * FPS)):
            proc.stdin.write(build_frame(i / FPS, spec).tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        code = proc.wait()
    if code != 0:
        sys.stderr.write(err[-2000:])
        raise SystemExit(f"ffmpeg exit {code}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", choices=sorted(CARDS), default="cs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seconds", type=float, default=15.0)
    args = ap.parse_args()

    spec = CARDS[args.card]()
    check_glyphs("".join(r["name"] + r["meta"] for r in spec["rows"])
                 + spec["hook"] + spec["point"] + spec["point2"])
    check_safe_areas(spec)

    out = Path(args.out) if args.out else (
        ROOT / "outputs" / "reels" / f"goaliq_{args.card}_reel.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    encode(out, spec, args.seconds)
    print(f"REEL {args.card} {W}x{H} {args.seconds:.0f}s -> {out} "
          f"({out.stat().st_size / 1024:.0f} kt)")
    print(f"  data {spec['generated']}")
    for i, r in enumerate(spec["rows"], 1):
        print(f"  {i}. {r['name']} ({r['meta']}) {r['val']}")
    print(f"  kolmas ruutu: {spec['point']} {spec['point2']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
