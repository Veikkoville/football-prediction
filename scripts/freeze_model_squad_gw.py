"""Beat the Model V2 vaihe a: mallin joukkueen deadline-freeze (13.8).

Lukitsee mallin rivin data/model_squad_frozen/gw{N}.json:iin kun seuraavan
GW:n deadline on alle FREEZE_WINDOW_H päässä — SAMA ikkuna ja sama cron kuin
freeze_fpl_xp_gw.py:llä, jotta xP-freeze ja joukkuefreeze kuvaavat samaa
hetkeä (muuten "sinä vs malli" vertaisi kahta eri maailmantilaa).

Rivi tulee free_optimum():sta eli TÄSMÄLLEEN samasta funktiosta jota
/api/fantasy/model-squad, rate-teamin benchmark ja fit checker käyttävät.
Oma kopio optimoinnista tähän olisi toinen totuus mallin joukkueesta, ja
julkinen race-paneeli lukisi eri riviä kuin sivu näyttää.

Immutable: olemassa olevaa freezeä EI ylikirjoiteta. Koko V2:n väite on
"logged before kickoff, todistettavissa git-historiasta" — jälkikäteen
vaihdettu rivi tuhoaa sen kertaheitolla.

LAILLISUUSVAHTI (12.8:n oppi): SPL:n model squad julkaistiin sivulle
laittomana (kaksi seuraa yli 3/seura-katon), koska optimoija palautti
lähtötilansa kun yksikään vaihto ei tuottanut laillista joukkuetta. Sama
virhe tässä olisi pysyvä: laiton rivi jäätyisi kauden mittaiseksi
vastustajaksi eikä sitä saisi enää korjata ilman että immutable-lupaus
rikkoutuu. Siksi freeze REFUSOI laittoman rungon (exit 1) eikä lukitse sitä.

Exit 0 myös kun ei jäädytettävää; tekninen virhe tai laiton runko → 1.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config

FROZEN_DIR = config.PROJECT_ROOT / "data" / "model_squad_frozen"
FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ freeze job)"}
FREEZE_WINDOW_H = 30   # sama kuin freeze_fpl_xp_gw.py

SQUAD_QUOTA = {1: 2, 2: 5, 3: 5, 4: 3}   # GK/DEF/MID/FWD 15:ssä
MAX_PER_CLUB = 3
BUDGET_TENTHS = 1000   # 100.0m


def gw_xp(player: dict, gw: int) -> float:
    """Pelaajan xP TÄLLE kierrokselle (ei horisonttisumma).

    Kapteeni on aina kierroskohtainen valinta: horisonttisumma nostaisi
    kapteeniksi pelaajan jolla on hyvä ohjelma myöhemmin, vaikka hän olisi
    tässä kierroksessa heikoin. Palauttaa 0.0 jos kierrosta ei projektiossa.
    """
    for g in player.get("gameweeks") or []:
        if g.get("gw") == gw:
            return float(g.get("xp") or 0.0)
    return 0.0


def validate_squad(xi: list[dict], bench: list[dict]) -> list[str]:
    """Palauta rikkeet listana; tyhjä lista = laillinen runko.

    Tarkistetaan koko 15:n runko, ei pelkkää XI:tä — kattorike voi olla
    kokonaan penkillä ja se on silti laiton FPL-joukkue.
    """
    problems: list[str] = []
    squad = list(xi) + list(bench)
    if len(squad) != 15:
        problems.append(f"runko on {len(squad)} pelaajaa, pitää olla 15")
    if len({p["id"] for p in squad}) != len(squad):
        problems.append("rungossa on sama pelaaja kahdesti")

    pos_have: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    for p in squad:
        et = p.get("element_type")
        if et in pos_have:
            pos_have[et] += 1
    if pos_have != SQUAD_QUOTA:
        problems.append(
            f"positiojakauma {pos_have} != vaadittu {SQUAD_QUOTA}")

    per_club: dict[int, int] = {}
    for p in squad:
        per_club[p.get("club")] = per_club.get(p.get("club"), 0) + 1
    over = {c: n for c, n in per_club.items() if n > MAX_PER_CLUB}
    if over:
        problems.append(f"yli {MAX_PER_CLUB}/seura: {over}")

    cost = sum(int(p.get("price") or 0) for p in squad)
    if cost > BUDGET_TENTHS:
        problems.append(f"hinta {cost / 10:.1f}m yli {BUDGET_TENTHS / 10:.1f}m")

    # OPTIMAALISUUSVAHTI (14.8): laillinen ei riitä. 14.8 julkaistu malli-XI
    # oli täysin laillinen mutta hävisi omalle penkilleen 7.4 % — kuka tahansa
    # olisi voittanut "mallin" siirtämällä kaksi pelaajaa penkiltä avaukseen.
    # Freeze on immutable ja kestää koko kauden, joten se on viimeinen paikka
    # jossa tämän voi vielä pysäyttää.
    # Vaatii horisontti-xP:n; ilman sitä tarkistus ohitetaan eksplisiittisesti
    # (yksikkötestien kevyet poolirivit) — hiljainen KeyError-nielaisu tekisi
    # vahdista näennäisen.
    if len(squad) == 15 and all(p.get("xp_horizon_total") is not None
                                for p in squad):
        from src.models.fpl_rate_team import RateTeamError, optimal_xi
        try:
            best = sum(p["xp_horizon_total"] for p in optimal_xi(squad))
        except RateTeamError:
            best = None
        if best is not None:
            cur = sum(float(p.get("xp_horizon_total") or 0.0) for p in xi)
            if best > cur + 1e-6:
                problems.append(
                    f"XI häviää omalle penkilleen: paras jako {best:.2f} xP "
                    f"> jäädytettävä XI {cur:.2f} xP "
                    f"(+{best - cur:.2f}, {(best / cur - 1) * 100:+.1f} %)")
    return problems


def order_bench(bench: list[dict], gw: int) -> list[dict]:
    """FPL:n penkkijärjestys: GK omana slottinaan, kenttäpelaajat xP-laskevasti.

    Autosub-sääntö kohtelee penkin maalivahtia erikseen (hän tulee vain
    maalivahdin tilalle), joten järjestys EI ole pelkkä xP-lajittelu koko
    penkistä. Tämä järjestys jäätyy riviin ja vaiheen b gradaus lukee sen
    sellaisenaan — penkkijärjestyksen päättäminen vasta gradaushetkellä
    olisi jälkiviisautta.
    """
    gks = [p for p in bench if p.get("element_type") == 1]
    outfield = [p for p in bench if p.get("element_type") != 1]
    outfield.sort(key=lambda p: (-gw_xp(p, gw), p["id"]))
    return gks + outfield


def pick_captain(xi: list[dict], gw: int) -> tuple[dict, dict]:
    """(kapteeni, varakapteeni) = kierroksen kaksi korkeinta xP:tä XI:ssä.

    Tasapelin ratkaisee id, jotta sama pooli tuottaa aina saman rivin
    (freeze on todiste, ei saa heilua ajokerroittain).
    """
    ranked = sorted(xi, key=lambda p: (-gw_xp(p, gw), p["id"]))
    return ranked[0], ranked[1]


def slim(p: dict, gw: int) -> dict:
    return {"id": p["id"], "web_name": p.get("web_name"),
            "team_short": p.get("team_short"), "pos": p.get("element_type"),
            "club": p.get("club"), "price": p.get("price"),
            "xp": round(gw_xp(p, gw), 3)}


def next_freeze_gw(events: list[dict], now: _dt.datetime):
    """Seuraava deadline freeze-ikkunassa → (gw, deadline) tai None."""
    for ev in events:
        if ev.get("finished"):
            continue
        dl = _dt.datetime.fromisoformat(
            str(ev.get("deadline_time", "")).replace("Z", "+00:00"))
        if dl > now and (dl - now) <= _dt.timedelta(hours=FREEZE_WINDOW_H):
            return int(ev["id"]), dl
    return None


def main() -> int:
    try:
        r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                         timeout=30)
        r.raise_for_status()
        events = r.json().get("events") or []
    except Exception as e:
        print(f"VIRHE: bootstrap-haku epäonnistui: {e!r}")
        return 1

    now = _dt.datetime.now(_dt.timezone.utc)
    nxt = next_freeze_gw(events, now)
    if nxt is None:
        print("Ei deadlinea freeze-ikkunassa — ei jäädytettävää.")
        return 0
    gw, dl = nxt

    out = FROZEN_DIR / f"gw{gw}.json"
    if out.exists():
        print(f"GW{gw} on jo jäädytetty — ei ylikirjoiteta (immutable).")
        return 0

    # Sama polku kuin /api/fantasy/model-squad — ei omaa optimointia.
    from src.models.fpl_rate_team import (
        RateTeamError, build_context, free_optimum)
    try:
        xp_data, _bootstrap, pool, _by_id = build_context()
        free = free_optimum(pool, str(xp_data["meta"].get("generated_at")))
    except RateTeamError as e:
        print(f"VIRHE: mallin runkoa ei saatu ({e.detail}).")
        return 1

    xi, bench = list(free.get("xi") or []), list(free.get("bench") or [])
    if not xi or len(bench) != 4:
        print(f"VIRHE: runko vajaa (XI {len(xi)}, penkki {len(bench)}).")
        return 1

    problems = validate_squad(xi, bench)
    if problems:
        print("VIRHE: optimoija palautti LAITTOMAN rungon — ei jäädytetä:")
        for p in problems:
            print(f"  - {p}")
        return 1

    bench = order_bench(bench, gw)
    cap, vice = pick_captain(xi, gw)
    cost = sum(int(p.get("price") or 0) for p in xi + bench)

    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "meta": {
            "gw": gw,
            "deadline": dl.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "frozen_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "projection_generated_at": xp_data.get("meta", {}).get("generated_at"),
            "cost": round(cost / 10, 1),
            "xi_xp_horizon": round(float(free.get("xi_xp") or 0.0), 2),
            "xi_xp_gw": round(sum(gw_xp(p, gw) for p in xi), 2),
            "optimal_proven": bool(free.get("proven")),
            # Malli ei pelaa chippejä (spec) — kerrotaan datassa asti, jotta
            # paneeli ei joudu arvaamaan sitä copyn perusteella.
            "chip": None,
        },
        "captain": cap["id"],
        "vice_captain": vice["id"],
        "xi": [slim(p, gw) for p in xi],
        "bench": [slim(p, gw) for p in bench],
    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"OK: GW{gw} mallin runko jäädytetty "
          f"({cost / 10:.1f}m, kapteeni {cap.get('web_name')}, "
          f"XI xP {sum(gw_xp(p, gw) for p in xi):.2f}, deadline {dl}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
