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

ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(ROOT_FOR_IMPORT))

from src.models.fpl_club_best import club_best_rows, gap_text  # noqa: E402

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

        # Erikoistilannemerkinnat (P = pilkut, FK = vapaapotkut). Selainkortti
        # piirtaa nama jo; ilman niita PIL-versio ei ollut sama kortti, mika
        # nakyi pikselidiffina viikkopostauksen korttia vastaan (9.8).
        for b in (r.get("badges") or []):
            bw = d.textlength(b, font=f_tag) + 14
            d.rectangle([x, cy - 14, x + bw, cy + 14], outline=AMBER, width=1)
            d.text((x + 7, cy - 9), b, font=f_tag, fill=AMBER)
            x += bw + 8

        if r.get("mid"):
            f_mid = _shrink(d, r["mid"], 24, 190, 14, FONT_MED)
            d.text((fx_right - d.textlength(r["mid"], font=f_mid),
                    cy - f_mid.size * 0.55), r["mid"], font=f_mid, fill=MUTED)

        val = r["value"]
        d.text((W - MX - d.textlength(val, font=f_val), cy - 36 * 0.58), val,
               font=f_val, fill=AMBER if first else CREAM)

    # Kahva varaa oikean laidan; alatunnisteen 1. rivi jakaa saman rivin sen
    # kanssa. Ilman kutistusta liian pitka teksti piirtyy kahvan PAALLE --
    # niin kavi 9.8 kun defence-kortin lahdemerkintaan lisattiin puuttuvat
    # seurat. Teksti ei saa hukkua siihen etta joku pidentaa sita myohemmin.
    f_handle = _font(FONT_BOLD, 20)
    handle_w = d.textlength("@goaliqapp", font=f_handle)
    foot_max = W - MX - handle_w - 24 - MX
    f_foot = _shrink(d, spec["footNote"], 20, foot_max, 13, FONT_MED)
    d.text((MX, h - 88), spec["footNote"], font=f_foot, fill=MUTED)
    d.text((W - MX - handle_w, h - 88), "@goaliqapp", font=f_handle, fill=AMBER)
    f_foot2 = _shrink(d, spec["footNote2"], 17, W - 2 * MX, 11, FONT_MED)
    d.text((MX, h - 54), spec["footNote2"], font=f_foot2, fill=MUTED)
    d.rectangle([0, h - 8, W, h], fill=AMBER)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG")
    return out_path


# ---------------------------------------------------------------------------
# Datarakentajat
# ---------------------------------------------------------------------------
def _xp_payload() -> dict:
    """Taysi xP-projektio korttigeneraattorille.

    🔴 14.8 BUGI: kortit lukivat JULKISTA /api/fantasy/xp-endpointia, joka on
    premium-portin takana MASKATTU top-10-teaseriksi (meta.masked=true, 10
    riviä 507:sta). Kortit siis rakennettiin myyntipinnasta eika omasta
    datasta. `xp`-kortille se sattui olemaan oikein — top 10 on top 10 —
    mutta `value`-kortti ("best xP per million") oli SYSTEMAATTISESTI vaara:
    vastine asuu halvoissa pelaajissa, ja ne on maskattu pois maaritelman
    nojalla. Kortti siis vastasi kysymykseen "kuka kymmenesta kalleimmasta on
    vahiten kallis". Se ehti olla kaytossa 9.8 alkaen.
    Vikaluokka on sama kuin muistiinpanossa "maski katkaisee ilmaispinnan
    hiljaa": tyhja tai typistetty lista ei ole virhe, se on uskottava vastaus.

    Lahde on nyt repon artefakti — sama tiedosto jonka API servaa, ilman
    maskia. Verkkohaku jaa varalle jos ajetaan repon ulkopuolelta, ja
    KUMPIKIN polku kertoo itsestaan aanekkaasti: hiljainen fallback
    maskattuun dataan olisi tasan tama bugi uudelleen.
    """
    import urllib.request

    p = DATA / "fpl_xp_projections.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        n = len(data.get("players") or [])
        print(f"[data] repon artefakti: {n} pelaajaa (maskaamaton)")
        return data
    req = urllib.request.Request(
        "https://api.goaliq.app/api/fantasy/xp",
        headers={"User-Agent": "Mozilla/5.0 goaliq-card-gen"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    n = len(data.get("players") or [])
    if data.get("meta", {}).get("masked"):
        raise SystemExit(
            f"VIRHE: API palautti MASKATUN teaserin ({n} pelaajaa). Kortteja ei "
            f"rakenneta myyntipinnasta — aja tama repossa, jolloin "
            f"data/fpl_xp_projections.json on kaytettavissa.")
    print(f"[data] API: {n} pelaajaa")
    return data


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

    # KAKSI ERI KYSYMYSTA, ja ne antavat eri jarjestyksen heti kun ikkunassa on
    # tupla- tai blankkiviikkoja:
    #   avg   = "kuinka hyva puolustus on YHDESSA ottelussa" (keskiarvo)
    #   total = "montako puhdasta peliä ikkunasta on odotettavissa" (summa)
    # FPL:ssa jalkimmainen on yleensa se paatos jota ollaan tekemassa, mutta
    # se palkitsee tuplaviikosta -- kumpikin on oikea vastaus eri kysymykseen,
    # joten kortti KERTOO kumpaa se nayttaa eika jata sita arvattavaksi.
    if args.metric == "total":
        ranked = sorted(((t, sum(v) / 100.0, len(v)) for t, v in acc.items()),
                        key=lambda x: x[1], reverse=True)[:args.top]
        value = lambda v: f"{v:.2f}"          # noqa: E731
        vlabel, sub = "xCS", "expected clean sheets in the window"
    else:
        ranked = sorted(((t, sum(v) / len(v), len(v)) for t, v in acc.items()),
                        key=lambda x: x[1], reverse=True)[:args.top]
        # .0f pyoristaa parilliseen (46.5 -> "46"), mika nayttaa lukijasta
        # yhden pienelta virheelta. Puolikkaat ylospain kuten ihminen odottaa.
        value = lambda v: f"{int(v + 0.5)}%"  # noqa: E731
        vlabel, sub = "CS%", "average clean sheet probability per fixture"

    span = f"GW{lo}" if lo == hi else f"GW{lo}-{hi}"
    return {
        "title": f"BEST CLEAN SHEET ODDS {span}",
        "subtitle": sub,
        "nameLabel": "TEAM",
        "midLabel": "FIXTURES",
        "valueLabel": vlabel,
        "footNote": "GoalIQ match model, logged before kickoff",
        "footNote2": "model projections, not betting advice",
        "rows": [{"rank": i + 1, "name": t, "mid": f"{n}", "value": value(v)}
                 for i, (t, v, n) in enumerate(ranked)],
        "file": f"goaliq-cs-{span.lower()}-{args.metric}.png",
    }


def card_defence(args) -> dict:
    """Vahiten xG:ta paastaneet.

    KOLME ASIAA JOTKA KORTIN ON SANOTTAVA, koska se matkustaa yksin ilman
    sivun ymparoivaa tekstia:
      1. Otos on KOKO edellinen kausi (38 ottelua/joukkue), ei alkanut kausi.
      2. xg_pm SISALTAA rangaistuspotkut -- vain vyohykesarakkeet jattavat ne
         pois (build_understat_team_defence.py lisaa xG:n ennen penalty-
         continueta).
      3. Mukana on vain ne joukkueet joilla on kauden data: nousijat puuttuvat
         kokonaan, eli nousija EI VOI nakya listalla. Ilman tata lukija
         paattelee etta nousijoiden puolustus on huono, vaikka se on
         mittaamatta. Sama sokea piste kaatoi /fpl/defence-sivun 8.8.
    Arvot luetaan metasta, jotta kortti ei voi erkaantua datasta.
    """
    d = _load("understat_team_defence_2526.json")
    meta = d.get("meta", {})
    teams = [t for t in d.get("teams", []) if t.get("xg_pm") is not None]
    ranked = sorted(teams, key=lambda t: float(t["xg_pm"]))[:args.top]
    season = meta.get("season", "last season")
    promoted = meta.get("promoted_no_data") or []
    n_have, n_all = len(teams), meta.get("n_current_teams") or len(teams)
    sub = f"{season} full season, per match, penalties included"
    foot = f"{n_have} of {n_all} clubs"
    if promoted:
        foot += f", no data yet: {', '.join(promoted)}"
    # "own xG model" tarkoittaa koodissa UNDERSTATIN omaa mallia
    # (build_understat_shots.py: "Understat runs its own xG model"). Sivulla
    # ymparoiva teksti kantaa sen, mutta kortti matkustaa yksin ja siina se
    # luki kuin malli olisi meidan. Lahde nimetaan, koska luvut EIVAT tasmaa
    # Optan eivatka FotMobin kanssa (mitattu 9.8: mediaani +11.6 % FotMobiin).
    foot2 = ("Understat xG, not Opta · free at goaliq.app, "
             "not betting advice")
    return {
        "title": "FEWEST XG CONCEDED",
        "subtitle": sub,
        "nameLabel": "TEAM",
        "valueLabel": "XGC",
        "footNote": foot,
        "footNote2": foot2,
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
    # Pariteetti sivun napin kanssa: samat suodattimet, ja ne KERROTAAN
    # alaotsikossa. Suodatettu kortti joka ei kerro suodatustaan on
    # harhaanjohtava jaettuna.
    if args.pos:
        want = args.pos.upper()
        rows = [p for p in rows if str(p[idx["pos"]]).upper() == want]
    if args.team:
        want_t = args.team.upper()
        rows = [p for p in rows if str(p[idx["team"]]).upper() == want_t]
    if not rows:
        raise SystemExit("Suodattimet eivat jata yhtaan pelaajaa.")
    n_pool = len(rows)
    rows.sort(key=lambda p: p[k], reverse=True)
    rows = rows[:args.top]
    label = args.sort.upper()
    fmt = (lambda v: str(int(v))) if all(
        float(p[k]).is_integer() for p in rows) else (lambda v: f"{v:.2f}")
    return {
        "title": f"TOP {args.top} BY {label}",
        "subtitle": " · ".join(
            [x for x in (args.pos.upper() if args.pos else "",
                         args.team.upper() if args.team else "",
                         f"{args.min_mins}+ mins" if args.min_mins else "",
                         f"{n_pool} players") if x]),
        "nameLabel": "PLAYER",
        "valueLabel": label,
        "footNote": "free FPL stats at goaliq.app",
        "footNote2": "official FPL API and shot-level data, not betting advice",
        "rows": [{"rank": i + 1, "name": str(p[idx["name"]]),
                  "tag": str(p[idx["pos"]]), "team": str(p[idx["team"]]),
                  "value": fmt(float(p[k]))}
                 for i, p in enumerate(rows)],
        "file": "goaliq-stats-" + "-".join(
            [x for x in (args.sort, (args.pos or "").lower(),
                         (args.team or "").lower()) if x]) + ".png",
    }


def card_xp(args) -> dict:
    """Seuraavan gameweekin xP-top: viikkopostauksen kortti.

    Siirretty tanne goaliq-appin outputs/gen_fpl_xp_list.py:sta 9.8, jotta
    samalle layoutille ei jaa kolmatta erillista renderoijaa. Data on sama
    live-endpoint kuin ennen, joten kortti ja webin Captain ranker nayttavat
    samat luvut.
    """
    data = _xp_payload()
    gw = data["meta"]["next_gameweek"]
    rows = []
    for p in data.get("players", []):
        g = next((g for g in (p.get("gameweeks") or []) if g.get("gw") == gw),
                 None)
        if not g:
            continue
        opps = g.get("opponents") or []
        fx = ", ".join(f"{o['opp']} ({o['venue']})" for o in opps) if opps             else "Blank"
        sp = p.get("set_pieces") or {}
        badges = []
        if isinstance(sp.get("pens"), (int, float)) and sp["pens"] <= 2:
            badges.append("P")
        if isinstance(sp.get("fk"), (int, float)) and sp["fk"] <= 2:
            badges.append("FK")
        rows.append({"name": p["web_name"], "tag": p["pos"],
                     "team": p["team_short"], "mid": fx,
                     "_xp": float(g.get("xp") or 0.0), "badges": badges})
    if not rows:
        raise SystemExit(f"Ei xP-rivejä GW{gw}:lle.")
    rows.sort(key=lambda r: r["_xp"], reverse=True)
    rows = rows[:args.top]
    return {
        "title": f"GAMEWEEK {gw} TOP {len(rows)}",
        "subtitle": "expected points, GoalIQ match model",
        "nameLabel": "PLAYER",
        "midLabel": "FIXTURE",
        "valueLabel": "xP",
        "footNote": "logged before kickoff, graded in public",
        "footNote2": "model projections, not betting advice",
        "rows": [dict(r, rank=i + 1, value=f"{r['_xp']:.2f}")
                 for i, r in enumerate(rows)],
        "file": f"goaliq_xp_gw{gw}_top{len(rows)}.png",
    }


def _tier_subtitle(args, n_gw: int, pos_label: str, cap: int) -> str:
    """Alaotsikko kertoo TASMALLEEN sen saannon jolla rivit valittiin.

    Jos saantoa ei kirjoiteta nakyviin, lukija ei voi tietaa miksi joku puuttuu
    - ja juuri se kaatoi ensimmaisen version (Welbeck putosi minuuttilattiaan
    jota kortilla ei lukenut missaan)."""
    yksikko = pos_label.lower()[:-1]
    osat = [f"next {n_gw} GW"]
    if args.max_price:
        osat.append(f"every {yksikko} at {args.max_price:.1f}m or less")
        # Hintakaton kanssa rank-cap on ERI rajaus ja se on sanottava erikseen.
        if args.rank_cap:
            osat.append(f"free top {cap}")
    elif args.rank_cap:
        # 17.8: tama haara sanoi saannon jo itse, ja alla ollut erillinen
        # `if args.rank_cap` lisasi sen TOISEN KERRAN. Kortille renderoityi
        # "every forward in the free top 100, free top 100". Loytyi vasta kun
        # kortti katsottiin kuvana - koodista se ei nay, koska kumpikin haara
        # on erikseen oikein.
        osat.append(f"every {yksikko} in the free top {cap}")
    return ", ".join(osat)


def card_price_tier(args) -> dict:
    """Yhden pelipaikan hinta vs pisteet, VAIN tarkistettavissa olevilla riveilla.

    Villen tilaus 15.8: "joku hintakategorian hyokkaajat tms."

    ALKUPERAINEN KULMA KAATUI MITTAUKSEEN, ja se on syyta lukea ennen kuin
    tata kayttaa uudelleen: alle 5,0 M£:n hyokkaajia on 14, mutta EI YHDELLA
    NIISTA ole projisoitua avauspaikkaa (xmins 34, 19, 19, 19, ...). Luvut
    eivat myoskaan ole projektioita vaan hintaprioria: viidella heista on
    identtinen 7.3 xP6, koska he ovat `no_history`-pelaajia jotka saavat saman
    kovakoodatun 38 %:n aloitustodennakoisyyden. Enemmisto on nousijaseuroista,
    eli "halpaa hyokkaajaa ei ole" olisi kertonut MEIDAN sokeasta pisteesta
    eika pelista.

    TARKISTETTAVUUS ON SISAANRAKENNETTU: `--rank-cap` pudottaa rivit jotka
    eivat mahdu ilmaissivun `/fpl/expected-points` top-100:aan. Ilman sita
    kortti nimeaisi pelaajia joita lukija ei voi tarkistaa mistaan — tasan se
    vika joka blokkasi kaksi tekstia 14.-15.8.
    """
    data = _xp_payload()
    players = data.get("players") or []
    n_gw = len(((players[0] if players else {}).get("gameweeks")) or []) or 6

    ranked = sorted(players, key=lambda p: -float(p.get("xp_horizon_total") or 0))
    cap = args.rank_cap or len(ranked)
    checkable = {p.get("id") or p.get("web_name") for p in ranked[:cap]}

    rows = []
    for p in ranked:
        if args.pos and p.get("pos") != args.pos:
            continue
        if (p.get("id") or p.get("web_name")) not in checkable:
            continue
        price = float(p.get("price") or 0)
        tot = float(p.get("xp_horizon_total") or 0)
        if price <= 0 or tot <= 0:
            continue
        # Hintakatto tekee kortista YHDEN johdonmukaisen kysymyksen.
        # Villen havainto 15.8: "sekava etta tutkii 8 milj hyokkaajia ja sit
        # yhtakkia haaland vain ylempana <- missa asiayhteys? paljon kalliimpi."
        # Han on oikeassa: ilman kattoa kortti sekoitti kaksi eri kysymysta
        # (kuka on paras vs kuka on paras rahoilla) ja rivit 1-2 vastasivat eri
        # kysymykseen kuin rivit 3-9. Katto on myos LUKIJAN tarkistettavissa:
        # hinta on FPL:n omaa julkista dataa.
        if args.max_price and price > args.max_price:
            continue
        # 🔴 EI MINUUTTILATTIAA, ja tama on tietoinen paatos (15.8).
        # Ensimmainen versio suodatti xmins >= 60 "projisoituihin aloittajiin".
        # Julkaisutarkistaja loysi etta se pudotti Welbeckin (CHE, 6.0m, 19.1)
        # jonka xmins on 59 - yhden alle rajan - vaikka kortilla oli Joao Pedro
        # 62:lla. Lukija joka avaa linkin ja suodattaa hyokkaajat nakee rivin
        # jota kortilla ei ole, eika kortti selita miksi. Rajan puolustaminen
        # yhden minuutin tarkkuudella on mahdotonta.
        #
        # Sen sijaan saanto on nyt sellainen jonka lukija voi TARKISTAA sivulta:
        # "jokainen hyokkaaja ilmaisen top 100:n sisalla". xmins nakyy omana
        # sarakkeenaan, joten rotaatioriski on nakyvissa eika piilotettuna.
        # 17.8: `tag` on TYHJA tarkoituksella. Se piirtyy merkkina nimen
        # viereen (ks. rivi ~150), ja aiemmin tassa oli hinta - joka menee
        # samalla `value`ksi oikean reunan PRICE-sarakkeeseen. Kortille
        # renderoityi siis hinta KAHDESTI joka rivilla ("Haaland [15.5m] MCI
        # ... 15.5m"). Muut korttityypit kayttavat `tag`ia pelipaikalle, joten
        # tama oli ainoa jossa sama arvo tuli kahteen kenttaan. Loytyi kuvasta,
        # ei koodista.
        rows.append({"name": p["web_name"], "tag": "", "_price": f"{price:.1f}m",
                     "team": p["team_short"],
                     "mid": f"{tot:.1f} xP · {float(p.get('xmins') or 0):.0f} min",
                     "_v": tot, "badges": []})
    if not rows:
        raise SystemExit("Ei rivejä price-tier-kortille.")
    rows.sort(key=lambda r: r["_v"], reverse=True)
    rows = rows[:args.top]
    pos_label = {"FWD": "FORWARDS", "MID": "MIDFIELDERS",
                 "DEF": "DEFENDERS", "GKP": "GOALKEEPERS"}.get(args.pos, "PLAYERS")
    return {
        "title": f"{pos_label}: PRICE VS POINTS",
        "subtitle": _tier_subtitle(args, n_gw, pos_label, cap),
        "nameLabel": "PLAYER",
        "midLabel": "TOTAL / EXP. MINUTES",
        "valueLabel": "PRICE",
        "footNote": "every row is on goaliq.app/fpl/expected-points, free",
        "footNote2": "model projections, not betting advice",
        "rows": [dict(r, rank=i + 1, value=r["_price"])
                 for i, r in enumerate(rows)],
        "file": f"goaliq_pricetier_{(args.pos or 'all').lower()}_{n_gw}gw.png",
    }


def card_value(args) -> dict:
    """xP per miljoona horisontin yli: hinta-tehokkuuskortti.

    Lisatty 9.8 koska r/FantasyPL-postaus tasta kulmasta oli se joka toimi:
    premiumit ovat parhaita pelaajia ja huonointa vastinetta. Kortti on IG:ta
    ja Blueskyta varten, joissa kuva on formaatti eika liite.

    --min-mins suodattaa avaajiin (oletus 60 xmins): ilman sita listan
    valtaisivat vaihtomiehet, joiden pieni xP jaettuna 4.0 miljoonalla nayttaa
    tehokkuudelta. Sama rajaus kuin postauksessa, jotta luvut tasmaavat.
    """
    data = _xp_payload()
    players = data.get("players") or []
    n_gw = len(((players[0] if players else {}).get("gameweeks")) or []) or 6
    floor = args.min_mins if args.min_mins and args.min_mins < 90 else 60
    rows = []
    for p in players:
        price = float(p.get("price") or 0)
        tot = float(p.get("xp_horizon_total") or 0)
        if price <= 0 or tot <= 0:
            continue
        if float(p.get("xmins") or 0) < floor:
            continue
        rows.append({"name": p["web_name"], "tag": p["pos"],
                     "team": p["team_short"],
                     "mid": f"{price:.1f}m · {tot:.1f} xP",
                     "_v": tot / price, "badges": []})
    if not rows:
        raise SystemExit("Ei rivejä value-kortille.")
    rows.sort(key=lambda r: r["_v"], reverse=True)
    rows = rows[:args.top]
    return {
        "title": f"BEST VALUE, NEXT {n_gw} GW",
        "subtitle": f"expected points per million, {floor}+ min starters",
        "nameLabel": "PLAYER",
        "midLabel": "PRICE / TOTAL",
        "valueLabel": "xP/m",
        "footNote": "logged before kickoff, graded in public",
        "footNote2": "model projections, not betting advice",
        "rows": [dict(r, rank=i + 1, value=f"{r['_v']:.2f}")
                 for i, r in enumerate(rows)],
        "file": f"goaliq_value_{n_gw}gw_top{len(rows)}.png",
    }


def card_club_best(args) -> dict:
    """Jokaisen seuran paras pelaaja YHDESSA positiossa, ennustetuilla pisteilla.

    KULMA (Villen idea 14.8, WGTA_FPL:n talismaani-kortin muoto). Se kortti
    listasi joukkueittain yhden pelaajan VIIME kauden pisteilla ja osuudella
    seuran pisteista. Sama muoto, eri data: meilla luku on ETEENPAIN katsova
    ennuste, ja "osuus" korvautuu erolla saman seuran ja saman position
    kakkoseen. Se on kysymys johon menneet pisteet eivat vastaa: onko tama
    seuran ainoa vaihtoehto talta paikalta vai yksi monesta.

    🔴 KAIKKI 20 SEURAA, EI MINUUTTILATTIAA. Aiempi versio suodatti
    xmins >= 60 ja tuotti hyokkaajakortin jossa oli 10 seuraa 20:sta —
    otsikko olisi luvannut "every club" ja kuva nayttanyt puolet. Lattian
    sijaan seuran paras kelpaa sellaisenaan: xP sisaltaa jo minuutit, joten
    vahan pelaava nousee seuransa karkeen vain jos seuralla ei ole ketaan
    parempaa, ja se on kortin kannalta TOSI vastaus.

    🔴 "?"-MERKKI ON PAKOLLINEN REHELLISYYSLIPPU. Pelaaja jolla ei ole
    Valioliigaminuutteja saa roolinsa hintapriorista eika mallilta. Nousijoiden
    riveilla se on saanto eika poikkeus, ja ilman merkkia kortti esittaisi
    priorin ennusteena. Sama periaate kuin data_basis-kentalla API:ssa.
    """
    pos = (args.pos or "").upper()
    if pos not in ("GKP", "DEF", "MID", "FWD"):
        raise SystemExit(
            "club-best vaatii --pos GKP|DEF|MID|FWD. Kortti on per positio: "
            "20 seuraa x 4 positiota olisi 80 rivia eika luettava kuva.")

    data = _xp_payload()
    players = data.get("players") or []
    n_gw = len(((players[0] if players else {}).get("gameweeks")) or []) or 6

    # 🔴 JAETTU LASKENTA. Alatunniste ohjaa lukijan /fpl/club-best-sivulle
    # todistamaan nama luvut. Jos kortti ja sivu laskisivat ne erikseen, ne
    # voisivat ajautua erilleen ja vaite kaatuisi tasan silla reitilla jolla
    # se piti todistaa. Ks. src/models/fpl_club_best.py.
    src_rows = club_best_rows(players, pos)
    if not src_rows:
        raise SystemExit(f"Ei rivejä positiolle {pos}.")

    rows = []
    for r in src_rows:
        # LUOTTAMUSINDIKAATTORI (Villen saanto 14.8): naytetaan vain kun se
        # kertoo jotain — `high` on oletus eika kaipaa selitysta. Tama kattaa
        # tapauksen jota "?" EI kata: pelaaja jolla on tayi PL-historia mutta
        # epavarmat minuutit (tyoparijako).
        price = f"{r['price']:.1f}m"
        if r["uncertain_minutes"]:
            price += f" · {r['xmins']:.0f} min"
        rows.append({
            "name": r["name"], "tag": r["club"], "team": price,
            "mid": gap_text(r), "_v": r["xp"],
            "badges": ["?"] if r["prior"] else [],
        })

    n_prior = sum(1 for r in rows if r["badges"])
    foot2 = "model projections, not betting advice"
    if n_prior:
        # "price prior" on mallijargonia julkisessa copyssa (vrt. `legal squad`
        # joka vuoti neljalle pinnalle). Sanotaan mita se tarkoittaa.
        foot2 = (f"? = no Premier League games yet, role guessed from price "
                 f"({n_prior} of {len(rows)}) · {foot2}")

    # 🔴 PAIVAYS ON TARKISTETTAVUUTTA, EI KOSMETIIKKAA. Lahdetiedosto
    # paivittyy useita kertoja paivassa (14.8: nelja refresh-committia), joten
    # ilman paivaysta lukija nakee huomenna eri luvut eika kortilla ole mitaan
    # joka selittaisi eron. Paivays luetaan artefaktin omasta leimasta eika
    # ajohetkesta: se kertoo milloin LUVUT syntyivat.
    gen = str(data.get("meta", {}).get("generated_at") or "")
    stamp = ""
    if len(gen) >= 10:
        y, m, dd = gen[:4], gen[5:7], gen[8:10]
        months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        try:
            stamp = f", as of {int(dd)} {months[int(m) - 1]}"
        except (ValueError, IndexError):
            stamp = ""
    first_gw = data.get("meta", {}).get("next_gameweek")
    window = (f"GW{first_gw}-{first_gw + n_gw - 1}" if first_gw
              else f"next {n_gw} gameweeks")
    return {
        "title": f"BEST {pos} AT EVERY CLUB",
        "subtitle": f"projected points, {window}{stamp}",
        "nameLabel": "PLAYER",
        "midLabel": "GAP TO CLUB'S 2ND",
        "valueLabel": "xP",
        # 🔴 REITTI ON KOLMAS YRITYS, ja kaksi edellista olivat vaarin.
        # (1) "goaliq.app/fpl" — se sivu renderoi listansa MASKATUSTA
        #     top-10-teaserista, eli 17 rivia 20:sta ei olisi tarkistettavissa.
        # (2) raaka JSON goaliq.app/data/... — reitti oli tosi mutta 1,3 MB
        #     JSON puhelimen selaimessa ei ole kenellekaan tarkistus vaan este.
        #     Portti ei nostanut sita koska se testasi vain etta URL vastaa 200.
        # (3) /fpl/club-best — ihmisluettava, ilmainen, ei kirjautumista, ja
        #     TASMALLEEN samat rivit koska laskenta on jaettu moduuli.
        # Huom miksi /fpl/expected-points EI kelpaa: se on `rows[:100]`, ja
        # nousijaseurojen karjet (Belloumi, Tchaouna, Florentino, Smith Rowe)
        # eivat mahdu koko liigan top-100:aan — eli tasan ne rivit joita
        # lukija todennakoisimmin haluaa tarkistaa puuttuisivat.
        "footNote": "every club, free at goaliq.app/fpl/club-best",
        "footNote2": foot2,
        "rows": [dict(r, rank=i + 1, value=f"{r['_v']:.1f}")
                 for i, r in enumerate(rows)],
        "file": f"goaliq_club_best_{pos.lower()}_{n_gw}gw.png",
    }


BUILDERS = {"cs": card_cs, "defence": card_defence, "stats": card_stats,
            "xp": card_xp, "value": card_value, "club-best": card_club_best,
            "price-tier": card_price_tier}
GW_CAPABLE = {"cs"}


def main() -> int:
    ap = argparse.ArgumentParser(description="GoalIQ share card generator")
    ap.add_argument("card", choices=sorted(BUILDERS))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--from-gw", type=int, default=1)
    ap.add_argument("--to-gw", type=int, default=6)
    ap.add_argument("--metric", choices=("avg", "total"), default="avg",
                    help="cs: avg = CS%% per ottelu, total = odotetut puhtaat "
                         "pelit ikkunassa")
    ap.add_argument("--sort", default="pts", help="stats: sarake (esim. xgi)")
    ap.add_argument("--min-mins", type=int, default=400,
                    help="stats: minimiminuutit")
    ap.add_argument("--pos", default=None, help="stats: GKP/DEF/MID/FWD")
    ap.add_argument("--team", default=None, help="stats: joukkuelyhenne (ARS)")
    ap.add_argument("--max-price", type=float, default=None,
                    help="price-tier: hintakatto miljoonissa (esim. 8.0)")
    ap.add_argument("--rank-cap", type=int, default=None,
                    help="price-tier: pudota rivit jotka eivat mahdu ilmaissivun "
                         "top-N:aan (tarkistettavuus). /fpl/expected-points = 100")
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
