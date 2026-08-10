# -*- coding: utf-8 -*-
"""IG Reels -video (9:16, 1080x1920) GoalIQ:n korttien ilmeella.

MIKSI TAMA ON TASSA TIEDOSTOSSA
Jakokortin renderoija (gen_share_card.py) on jo taalla, ja 9.8. paatettiin
etta Python-puolella on YKSI toteutus per layout. Video kayttaa tismalleen
samaa palettia, fonttia ja wordmarkia importtaamalla ne siita -> jos brandi
muuttuu, video ei jaa jalkeen omana kopiona.

LUVUT EIVAT OLE KOODISSA. Ne luetaan committatusta xP-artefaktista samalla
suodattimella jota copy lupaa (odotetut avaajat = xmins >= 60), joten video ei
voi vaittaa eri asiaa kuin sivu.

AANIRAITA: mykka AAC. Instagram kohtelee taysin aanetonta tiedostoa
epaluotettavasti (osa clienteista hylkaa), joten raita on olemassa mutta tyhja.

KAYTTO
    python scripts/gen_reel.py                 # value-reel, 15 s
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
STARTER_MINS = 60.0          # sama raja kuin copyn "expected starters only"
N_ROWS = 5


# ---------------------------------------------------------------- data
def load_rows(n: int = N_ROWS) -> list[dict]:
    doc = json.loads(XP.read_text(encoding="utf-8"))
    starters = [p for p in doc["players"]
                if p.get("xmins", 0) >= STARTER_MINS and p.get("price")]
    if not starters:
        raise SystemExit("VIRHE: 0 odotettua avaajaa artefaktissa — "
                         "video jaisi tyhjaksi eika kukaan huomaisi.")
    top = sorted(starters, key=lambda p: -(p["xp_horizon_total"] / p["price"]))
    rows = []
    for p in top[:n]:
        if p.get("status") != "a":
            # Loukkaantunut/epavarma karkeen = kuvassa lupaus jota data ei kanna.
            continue
        rows.append({
            "name": p["web_name"],
            "team": p["team_short"],
            "price": p["price"],
            "ppm": p["xp_horizon_total"] / p["price"],
        })
    if len(rows) < n:
        raise SystemExit(f"VIRHE: vain {len(rows)}/{n} status 'a' -rivia — "
                         "tarkista data ennen kuin video menee ulos.")
    return rows


def check_glyphs(text: str) -> None:
    """Kadioglu kirjoitetaan oikein tai ei lainkaan. Puuttuva glyfi piirtyy
    tyhjana laatikkona eika kaada mitaan, joten se tarkistetaan erikseen."""
    f = ImageFont.truetype(str(FONT_BOLD), 40)
    missing = f.getmask("").getbbox()
    for ch in set(text):
        if ch.isspace():
            continue
        if f.getmask(ch).getbbox() == missing and missing is not None:
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


def frame_hook(t: float) -> Image.Image:
    """0.0-2.6 s. Yksi vaite, ei lukuja. Alleviivaus kasvaa."""
    img = _base()
    d = ImageDraw.Draw(img)
    f = _f(FONT_BOLD, 92)
    lines = _wrap(d, "Your fourth defender is the cheapest points on the board.",
                  f, W - 160)
    y = H // 2 - (len(lines) * 112) // 2 - 60
    for ln in lines:
        d.text((80, y), ln, font=f, fill=CREAM)
        y += 112
    grow = max(0.0, min(1.0, (t - 0.35) / 0.9))
    if grow > 0:
        d.rectangle([80, y + 30, 80 + int((W - 160) * grow), y + 44], fill=AMBER)
    return img


def frame_table(t: float, rows: list[dict]) -> Image.Image:
    """2.6-9.4 s. Rivit ilmestyvat yksi kerrallaan."""
    img = _base()
    d = ImageDraw.Draw(img)
    # Ylareuna 0-250 px ja alareuna 1520-1920 px ovat Instagramin oman UI:n
    # alla (kayttajanimi, caption, napit). Kaikki sisalto pidetaan valissa.
    d.text((80, 300), "POINTS PER MILLION", font=_f(FONT_BOLD, 74), fill=AMBER)
    d.text((80, 392), "First six gameweeks", font=_f(FONT_MED, 40), fill=CREAM)
    d.text((80, 448), "Expected starters only", font=_f(FONT_MED, 36),
           fill=MUTED)

    top, row_h = 610, 180
    f_name, f_meta = _f(FONT_BOLD, 64), _f(FONT_MED, 38)
    f_val, f_rank = _f(FONT_BOLD, 72), _f(FONT_BOLD, 44)
    for i, r in enumerate(rows):
        appear = 0.45 + i * 0.85
        if t < appear:
            break
        y = top + i * row_h
        d.text((80, y + 26), str(i + 1), font=f_rank, fill=MUTED)
        d.text((170, y), r["name"], font=f_name, fill=CREAM)
        d.text((170, y + 76), f"{r['team']}   {r['price']:.1f}m",
               font=f_meta, fill=MUTED)
        val = f"{r['ppm']:.2f}"
        d.text((W - 80 - d.textlength(val, font=f_val), y + 18), val,
               font=f_val, fill=AMBER if i == 0 else CREAM)
        d.line([80, y + row_h - 26, W - 80, y + row_h - 26],
               fill=(60, 58, 54), width=2)
    return img


def frame_point(t: float) -> Image.Image:
    """9.4-12.2 s. Miksi lista ei ole pelkkia halpoja penkkimiehia."""
    img = _base()
    d = ImageDraw.Draw(img)
    f = _f(FONT_BOLD, 86)
    lines = _wrap(d, "Every one of them is expected to start.", f, W - 160)
    y = H // 2 - (len(lines) * 106) // 2 - 40
    for ln in lines:
        d.text((80, y), ln, font=f, fill=CREAM)
        y += 106
    if t > 10.4:
        f2 = _f(FONT_MED, 46)
        for ln in _wrap(d, "That is the whole trick.", f2, W - 160):
            d.text((80, y + 40), ln, font=f2, fill=AMBER)
            y += 60
    return img


def frame_end(t: float) -> Image.Image:
    """12.2-15.0 s. CTA. Ilmaissivu, ei tilia."""
    img = _base()
    d = ImageDraw.Draw(img)
    _wordmark(img, 620)
    f = _f(FONT_BOLD, 70)
    txt = "The full list is free"
    d.text(((W - d.textlength(txt, font=f)) / 2, 900), txt, font=f, fill=CREAM)
    f2 = _f(FONT_MED, 44)
    t2 = "No account, no sign-in"
    d.text(((W - d.textlength(t2, font=f2)) / 2, 1000), t2, font=f2, fill=MUTED)
    f3 = _f(FONT_BOLD, 56)
    t3 = "goaliq.app"
    if t > 13.0:
        d.text(((W - d.textlength(t3, font=f3)) / 2, 1130), t3, font=f3,
               fill=AMBER)
    return img


def build_frame(t: float, rows: list[dict]) -> Image.Image:
    if t < 2.6:
        return frame_hook(t)
    if t < 9.4:
        return frame_table(t, rows)
    if t < 12.2:
        return frame_point(t)
    return frame_end(t)


# ---------------------------------------------------------------- enkoodaus
def encode(out: Path, rows: list[dict], seconds: float = 15.0) -> Path:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    n = int(seconds * FPS)
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
        for i in range(n):
            proc.stdin.write(build_frame(i / FPS, rows).tobytes())
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
    ap.add_argument("--out", default=str(ROOT / "outputs" / "reels"
                                        / "goaliq_value_reel.mp4"))
    ap.add_argument("--seconds", type=float, default=15.0)
    args = ap.parse_args()

    rows = load_rows()
    check_glyphs("".join(r["name"] + r["team"] for r in rows))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    encode(out, rows, args.seconds)
    kb = out.stat().st_size / 1024
    print(f"REEL {W}x{H} {args.seconds:.0f}s -> {out} ({kb:.0f} kt)")
    for i, r in enumerate(rows, 1):
        print(f"  {i}. {r['name']} {r['team']} {r['price']:.1f}m "
              f"{r['ppm']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
