# -*- coding: utf-8 -*-
"""GoalIQ-jakokortti komentoriviltä — toistettava versio sivujen napista.

TAUSTA (Villen pyynto 9.8): sivujen "Share as image" tekee kortin siita mita
kayttaja on suodattanut. Omaan postaustahtiin tarvitaan sama kortti ilman
kasityota, jotta se ei ole joka kerta klikkailua.

LAYOUT on TASMALLEEN sama kuin selainkortissa (scripts/share_card_js.py) ja
SPA:ssa (web/pro-spa/src/lib/shareCard.ts): 1080 leveä, ROW_TOP 404, ROW_H 80,
sama paletti ja sama alatunniste. Jos muutat mittoja, muuta KAIKKI kolme --
muuten syntyy nelja erinakoista korttia samasta tuotteesta.

GAMEWEEK-IKKUNA (--from-gw / --to-gw) on mahdollinen VAIN siella missa data on
ottelukohtaista:
    cs        kylla  (data/fpl_cs_fdr.json, fixtures[].gameweek)
    defence   ei     (kauden aggregaatti per joukkue, ei GW-erittelya)
    stats     ei     (FPL:n kausisummat, ei GW-erittelya)
Naille kahdelle GW-ikkuna vaatisi uuden datalahteen; skripti sanoo sen
suoraan sen sijaan etta hyvaksyisi lipun ja jattaisi sen HILJAA huomiotta.

AJO:
    python scripts/gen_share_card.py cs --from-gw 1 --to-gw 6
    python scripts/gen_share_card.py defence
    python scripts/gen_share_card.py stats --sort xgi --top 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = ROOT / "outputs" / "cards"

# --- Layout: 1:1 share_card_js.py / shareCard.ts ---------------------------
W, MX = 1080, 60
ROW_TOP, ROW_H, FOOT_H = 404, 80, 146
INK, INK2 = (11, 10, 9), (20, 19, 17)
AMBER, CREAM, MUTED = (245, 197, 66), (243, 242, 242), (168, 162, 154)
LINE = (243, 242, 242, 34)
TAG_LINE = (243, 242, 242, 84)

_FONT_DIR = Path(
    "C:/users/vvsaa/documents/goaliq-app/node_modules/@expo-google-fonts"
    "/ibm-plex-mono"
)
FONT_BOLD = _FONT_DIR / "700Bold" / "IBMPlexMono_700Bold.ttf"
FONT_MED = _FONT_DIR / "500Medium" / "IBMPlexMono_500Medium.ttf"
WORDMARK = ROOT / "assets" / "brand" / "goaliq-wordmark-teletext.png"


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        # Fontin puuttuminen muuttaisi kortin ilmeen taysin ja hiljaa.
        raise SystemExit(f"Fonttia ei loydy: {path}")
    return ImageFont.truetype(str(path), size)


def _shrink(d, text, px, max_w, min_px, font_path):
    f = _font(font_path, px)
    while d.textlength(text, font=f) > max_w and px > min_px:
        px -= 2
        f = _font(font_path, px)
    return f


def render(spec: dict, out_path: Path) -> Path:
    rows = spec["rows"]
    h = ROW_TOP + len(rows) * ROW_H + FOOT_H

    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        grad.putpixel((0, y),
                      tuple(int(a + (b - a) * t) for a, b in zip(INK, INK2)))
    canvas = grad.resize((W, h)).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    if WORDMARK.exists():
        wm_src = Image.open(WORDMARK).convert("RGBA")
        wm_h = 84
        wm = wm_src.resize(
            (int(wm_src.width * wm_h / wm_src.height), wm_h), Image.LANCZOS)
        canvas.alpha_composite(wm, ((W - wm.width) // 2, 64))
    else:
        f = _font(FONT_BOLD, 56)
        gw_w = d.textlength("GOAL", font=f)
        box, x0 = 76, (W - (gw_w + 14 + 76)) / 2
        d.text((x0, 72), "GOAL", font=f, fill=CREAM)
        d.rectangle([x0 + gw_w + 14, 64, x0 + gw_w + 14 + box, 64 + box],
                    fill=AMBER)
        f2 = _font(FONT_BOLD, 40)
        d.text((x0 + gw_w + 14 + (box - d.textlength("IQ", font=f2)) / 2, 82),
               "IQ", font=f2, fill=INK)
    d.rounded_rectangle([(W - 120) / 2, 176, (W + 120) / 2, 182],
                        radius=3, fill=AMBER)

    f_title = _font(FONT_BOLD, 60)
    title = spec["title"]
    d.text(((W - d.textlength(title, font=f_title)) / 2, 226), title,
           font=f_title, fill=CREAM)
    f_sub = _font(FONT_MED, 22)
    sub = spec["subtitle"]
    d.text(((W - d.textlength(sub, font=f_sub)) / 2, 306), sub,
           font=f_sub, fill=MUTED)

    f_col = _font(FONT_MED, 19)
    fx_right = W - MX - 180
    d.text((MX + 76, ROW_TOP - 34), spec.get("nameLabel", "PLAYER"),
           font=f_col, fill=MUTED)
    if spec.get("midLabel"):
        d.text((fx_right - d.textlength(spec["midLabel"], font=f_col),
                ROW_TOP - 34), spec["midLabel"], font=f_col, fill=MUTED)
    d.text((W - MX - d.textlength(spec["valueLabel"], font=f_col),
            ROW_TOP - 34), spec["valueLabel"], font=f_col, fill=MUTED)

    f_rank = _font(FONT_BOLD, 28)
    f_tag = _font(FONT_BOLD, 17)
    f_team = _font(FONT_MED, 20)
    f_val = _font(FONT_BOLD, 36)

    for i, r in enumerate(rows):
        y = ROW_TOP + i * ROW_H
        cy = y + ROW_H / 2
        first = i == 0
        d.rectangle([MX - 12, y + 4, W - (MX - 12), y + ROW_H - 4],
                    outline=AMBER if first else LINE, width=2 if first else 1)

        rk = str(r["rank"])
        d.text((MX + 34 - d.textlength(rk, font=f_rank), cy - 16), rk,
               font=f_rank, fill=AMBER if first else MUTED)

        x = MX + 76
        f_name = _shrink(d, r["name"], 32, 330, 20, FONT_BOLD)
        d.text((x, cy - f_name.size * 0.62), r["name"], font=f_name, fill=CREAM)
        x += d.textlength(r["name"], font=f_name) + 16

        if r.get("tag"):
            pw = d.textlength(r["tag"], font=f_tag) + 16
            d.rectangle([x, cy - 15, x + pw, cy + 15], outline=TAG_LINE, width=1)
            d.text((x + 8, cy - 10), r["tag"], font=f_tag, fill=CREAM)
            x += pw + 12

        if r.get("team"):
            d.text((x, cy - 10), r["team"], font=f_team, fill=MUTED)
            x += d.textlength(r["team"], font=f_team) + 12

        if r.get("mid"):
            f_mid = _shrink(d, r["mid"], 24, 190, 14, FONT_MED)
            d.text((fx_right - d.textlength(r["mid"], font=f_mid),
                    cy - f_mid.size * 0.55), r["mid"], font=f_mid, fill=MUTED)

        val = r["value"]
        d.text((W - MX - d.textlength(val, font=f_val), cy - 36 * 0.58), val,
               font=f_val, fill=AMBER if first else CREAM)

    f_foot = _font(FONT_MED, 20)
    d.text((MX, h - 88), spec["footNote"], font=f_foot, fill=MUTED)
    f_handle = _font(FONT_BOLD, 20)
    d.text((W - MX - d.textlength("@goaliqapp", font=f_handle), h - 88),
           "@goaliqapp", font=f_handle, fill=AMBER)
    d.text((MX, h - 54), spec["footNote2"], font=_font(FONT_MED, 17), fill=MUTED)
    d.rectangle([0, h - 8, W, h], fill=AMBER)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG")
    return out_path


# ---------------------------------------------------------------------------
# Datarakentajat
# ---------------------------------------------------------------------------
def _load(name: str) -> dict:
    p = DATA / name
    if not p.exists():
        raise SystemExit(f"Datatiedostoa ei loydy: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def card_cs(args) -> dict:
    """Puhtaan pelin todennakoisyys valitulla gameweek-ikkunalla."""
    d = _load("fpl_cs_fdr.json")
    lo, hi = args.from_gw, args.to_gw
    acc: dict[str, list[float]] = {}
    for fx in d.get("fixtures", []):
        gw = fx.get("gameweek")
        if gw is None or not (lo <= int(gw) <= hi):
            continue
        for side in ("home", "away"):
            team = fx.get(side)
            pct = fx.get(f"cs_{side}_pct")
            if team is None or pct is None:
                continue
            acc.setdefault(str(team), []).append(float(pct))
    if not acc:
        raise SystemExit(f"Ei otteluita valilla GW{lo}-{hi}.")
    # Keskiarvo, ei summa: eri joukkueilla voi olla eri maara otteluita
    # ikkunassa (tupla- ja blankkiviikot), ja summa palkitsisi pelimaarasta.
    ranked = sorted(((t, sum(v) / len(v), len(v)) for t, v in acc.items()),
                    key=lambda x: x[1], reverse=True)[:args.top]
    span = f"GW{lo}" if lo == hi else f"GW{lo}-{hi}"
    return {
        "title": f"BEST CLEAN SHEET ODDS {span}",
        "subtitle": "average clean sheet probability per fixture",
        "nameLabel": "TEAM",
        "midLabel": "FIXTURES",
        "valueLabel": "CS%",
        "footNote": "GoalIQ match model, logged before kickoff",
        "footNote2": "model projections, not betting advice",
        "rows": [{"rank": i + 1, "name": t, "mid": f"{n}", "value": f"{v:.0f}%"}
                 for i, (t, v, n) in enumerate(ranked)],
        "file": f"goaliq-cs-{span.lower()}.png",
    }


def card_defence(args) -> dict:
    d = _load("understat_team_defence_2526.json")
    teams = [t for t in d.get("teams", []) if t.get("xg_pm") is not None]
    ranked = sorted(teams, key=lambda t: float(t["xg_pm"]))[:args.top]
    return {
        "title": "FEWEST XG CONCEDED",
        "subtitle": "expected goals conceded per match, lowest is best",
        "nameLabel": "TEAM",
        "valueLabel": "XGC",
        "footNote": "shot-level data, own expected-goals model",
        "footNote2": "free at goaliq.app, not betting advice",
        "rows": [{"rank": i + 1, "name": str(t["team"]),
                  "value": f"{float(t['xg_pm']):.2f}"}
                 for i, t in enumerate(ranked)],
        "file": "goaliq-defence-xgc.png",
    }


def card_stats(args) -> dict:
    d = _load("fpl_player_stats.json")
    cols = d["meta"]["cols"]
    if args.sort not in cols:
        raise SystemExit(
            f"Tuntematon sarake {args.sort!r}. Vaihtoehdot: {', '.join(cols)}")
    idx = {c: i for i, c in enumerate(cols)}
    k = idx[args.sort]
    rows = [p for p in d["players"]
            if isinstance(p[k], (int, float)) and p[idx["mins"]] >= args.min_mins]
    rows.sort(key=lambda p: p[k], reverse=True)
    rows = rows[:args.top]
    label = args.sort.upper()
    fmt = (lambda v: str(int(v))) if all(
        float(p[k]).is_integer() for p in rows) else (lambda v: f"{v:.2f}")
    return {
        "title": f"TOP {args.top} BY {label}",
        "subtitle": f"{d['meta'].get('basis_label') or 'season totals'}"
                    f", min {args.min_mins} minutes",
        "nameLabel": "PLAYER",
        "valueLabel": label,
        "footNote": "free FPL stats at goaliq.app",
        "footNote2": "official FPL API and shot-level data, not betting advice",
        "rows": [{"rank": i + 1, "name": str(p[idx["name"]]),
                  "tag": str(p[idx["pos"]]), "team": str(p[idx["team"]]),
                  "value": fmt(float(p[k]))}
                 for i, p in enumerate(rows)],
        "file": f"goaliq-stats-{args.sort}.png",
    }


BUILDERS = {"cs": card_cs, "defence": card_defence, "stats": card_stats}
GW_CAPABLE = {"cs"}


def main() -> int:
    ap = argparse.ArgumentParser(description="GoalIQ share card generator")
    ap.add_argument("card", choices=sorted(BUILDERS))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--from-gw", type=int, default=1)
    ap.add_argument("--to-gw", type=int, default=6)
    ap.add_argument("--sort", default="pts", help="stats: sarake (esim. xgi)")
    ap.add_argument("--min-mins", type=int, default=400,
                    help="stats: minimiminuutit")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    gw_given = any(x.startswith("--from-gw") or x.startswith("--to-gw")
                   for x in sys.argv[1:])
    if gw_given and a.card not in GW_CAPABLE:
        # Hiljaa ohitettu lippu on pahempi kuin virhe: kortin otsikko
        # lupaisi ikkunan jota data ei kanna.
        raise SystemExit(
            f"--from-gw/--to-gw ei ole tuettu kortille {a.card!r}: sen data on "
            f"kauden aggregaatti ilman gameweek-erittelya. GW-ikkuna toimii: "
            f"{', '.join(sorted(GW_CAPABLE))}")

    spec = BUILDERS[a.card](a)
    out = Path(a.out) if a.out else OUT_DIR / spec["file"]
    p = render(spec, out)
    print(f"{spec['title']} ({len(spec['rows'])} rivia) -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
