"""Esikauden minuuttisyote (2.8.2026) — harjoitusottelut Sofascoresta.

MIKSI: mallin `xmins` ja `p_start` ovat esikaudella puhtaita arvioita. Ne
johdetaan viime kauden historiasta, eivatka ne tieda etta pelaaja on vaihtanut
seuraa, noussut aloituskokoonpanoon tai jaanyt penkille koko heinakuun. Juuri
minuutit ovat FPL:n suurin yksittainen virhelahde kauden alussa (vrt.
2.8. reply: Semenyo 87 min vs Cherki 47 min oli koko vastaus).

Harjoitusotteluiden minuutit ovat ainoa julkinen HAVAINTO tasta ennen GW1:ta.

MITA TAMA EI OLE: tama ei muuta mallia. Moduuli kerää datan ja raportoi sen;
xmins-syotto on erillinen muutos oman porttinsa takana (G1 backtest + Villen
nimetty GO), koska se muuttaisi julkaistuja xP-lukuja.

REHELLISYYSRAJOITE joka pitaa kantaa kaikkeen mita tasta johdetaan:
harjoitusottelut ovat heikko signaali. Rotaatio on rajua, vastus epatasaista,
kokeilijat mukana, eika 45 minuuttia heinakuussa tarkoita 90 minuuttia
elokuussa. Tama kertoo MITA TAPAHTUI, ei mita tapahtuu.

LAHDE: Sofascore (epavirallinen API). Kaytetaan repon olemassa olevaa
_hae-clientia, joka kiertaa 403:n TLS-fingerprintilla. Vain luku, kohtuullinen
tahti, ei rinnakkaisuutta.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict

from src.data.sofascore import _hae

API = "https://api.sofascore.com/api/v1"
PL_TOURNAMENT = 17
PL_SEASON_2627 = 96668
# Kohteliaisuusviive: tama on epavirallinen rajapinta eika sita saa hakata.
SLEEP_S = 0.6
# Turnauksen jalkeinen loma + paluu treeneihin. Sen sisalla pelatut
# harjoitusminuutit eivat kerro pelaajan roolista mitaan.
WC_REST_DAYS = 28


def _get(path: str) -> dict:
    r = _hae(f"{API}/{path}", timeout=25)
    time.sleep(SLEEP_S)
    return r.json()


def pl_teams(season_id: int = PL_SEASON_2627) -> list[dict]:
    """Kauden 20 PL-joukkuetta Sofascore-id:lla."""
    d = _get(f"unique-tournament/{PL_TOURNAMENT}/season/{season_id}/teams")
    return [
        {"id": t["id"], "name": t.get("name"), "short": t.get("shortName")}
        for t in d.get("teams", [])
        if isinstance(t.get("id"), int)
    ]


def is_friendly(event: dict) -> bool:
    name = ((event.get("tournament") or {}).get("name") or "").lower()
    return "friendly" in name


def team_friendlies(team_id: int, since_ts: int) -> list[dict]:
    """Joukkueen harjoitusottelut annetun aikaleiman jalkeen.

    Kaytetaan 'last' -syotetta: se sisaltaa PELATUT ottelut, joissa on
    tilastot. Tulevat friendlyt eivat kiinnosta minuuttisyotetta.
    """
    out: list[dict] = []
    for page in (0, 1):
        try:
            d = _get(f"team/{team_id}/events/last/{page}")
        except Exception:
            break
        evs = d.get("events", [])
        if not evs:
            break
        for e in evs:
            if not is_friendly(e):
                continue
            if (e.get("startTimestamp") or 0) < since_ts:
                continue
            out.append({
                "id": e["id"],
                "ts": e.get("startTimestamp"),
                "home": (e.get("homeTeam") or {}).get("name"),
                "away": (e.get("awayTeam") or {}).get("name"),
                "home_id": (e.get("homeTeam") or {}).get("id"),
                "away_id": (e.get("awayTeam") or {}).get("id"),
            })
    return out


@dataclass
class PlayerMinutes:
    sofascore_id: int
    name: str
    team: str
    country: str = ""
    matches: int = 0
    starts: int = 0
    minutes: int = 0
    per_match: list[int] = field(default_factory=list)

    @property
    def avg_minutes(self) -> float:
        return round(self.minutes / self.matches, 1) if self.matches else 0.0

    @property
    def start_rate(self) -> float:
        return round(self.starts / self.matches, 3) if self.matches else 0.0


def event_minutes(event_id: int) -> list[dict]:
    """Per-pelaaja minuutit yhdesta ottelusta.

    `substitute: True` = aloitti penkilta. Pelaajat joilla minutesPlayed
    puuttuu tai on 0 EIVAT ole rivi: he eivat pelanneet, eika nollaminuuttia
    saa laskea keskiarvoon (se painaisi vaihtopelaajan alas siita etta han
    oli mukana matkalla).
    """
    d = _get(f"event/{event_id}/lineups")
    rows: list[dict] = []
    for side in ("home", "away"):
        for p in (d.get(side) or {}).get("players", []):
            st = p.get("statistics") or {}
            mins = st.get("minutesPlayed")
            if not isinstance(mins, int) or mins <= 0:
                continue
            pl = p.get("player") or {}
            if not isinstance(pl.get("id"), int):
                continue
            rows.append({
                "sofascore_id": pl["id"],
                "name": pl.get("name") or pl.get("shortName") or "",
                "country": ((pl.get("country") or {}).get("name") or ""),
                "side": side,
                "minutes": mins,
                "started": not bool(p.get("substitute")),
            })
    return rows


WC_TOURNAMENT = 16
WC_SEASON_2026 = 58210


def wc_players_by_last_appearance() -> dict[int, str]:
    """Sofascore-pelaaja-id -> hanen VIIMEISEN MM-ottelunsa paivamaara.

    Miksi pelaajatasolla eika kansalaisuudella: ensimmainen versio liputti
    kansalaisuuden perusteella ja merkitsi 110/191 pelaajaa, joista 92
    englantilaista. Valtaosa PL:n englantilaisista ei ollut turnauksessa
    lainkaan, joten lippu olisi sulkenut pois yli puolet datasta ja tehnyt
    signaalista hyodyttoman. Vain oikeasti pelanneet lasketaan.
    """
    out: dict[int, str] = {}
    try:
        rounds = _get(
            f"unique-tournament/{WC_TOURNAMENT}/season/{WC_SEASON_2026}/events/last/0"
        ).get("events", [])
        for page in (1, 2, 3):
            more = _get(
                f"unique-tournament/{WC_TOURNAMENT}/season/{WC_SEASON_2026}"
                f"/events/last/{page}"
            ).get("events", [])
            if not more:
                break
            rounds += more
    except Exception:
        return out

    import datetime as _dt
    for e in rounds:
        ts = e.get("startTimestamp")
        if not ts:
            continue
        day = _dt.date.fromtimestamp(ts).isoformat()
        try:
            rows = event_minutes(e["id"])
        except Exception:
            continue
        for r in rows:
            pid = r["sofascore_id"]
            if day > out.get(pid, ""):
                out[pid] = day
    return out


def wc_last_match_dates() -> dict[str, str]:
    """Maa -> sen VIIMEISEN MM-ottelun paivamaara, omasta ennustelokista.

    Miksi lokista eika kovakoodattuna: loki sisaltaa kaikki 64 gradattua
    MM-ottelua tuloksineen, joten "kuinka pitkalle maa paasi" on siella
    faktana. Kovakoodattu vaihetaulukko vanhenisi ja voisi olla vaarin.
    """
    import config
    p = config.PROJECT_ROOT / "data" / "prediction_log.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8")).get("predictions", [])
    out: dict[str, str] = {}
    for r in rows:
        if r.get("competition") != "WC" or not r.get("result") or not r.get("date"):
            continue
        d = r["date"][:10]
        for team in (r.get("home_team"), r.get("away_team")):
            if team and d > out.get(team, ""):
                out[team] = d
    return out


def build(days_back: int = 45, teams: list[dict] | None = None,
          now_ts: int | None = None, progress=None) -> dict:
    """Kerää PL-joukkueiden harjoitusotteluiden minuutit."""
    now_ts = now_ts or int(time.time())
    since = now_ts - days_back * 86400
    teams = teams if teams is not None else pl_teams()

    seen_events: set[int] = set()
    agg: dict[int, PlayerMinutes] = {}
    team_by_sofa = {t["id"]: (t.get("short") or t.get("name") or "") for t in teams}
    events_used: list[dict] = []

    for i, t in enumerate(teams):
        if progress:
            progress(i + 1, len(teams), t.get("short"))
        try:
            fixtures = team_friendlies(t["id"], since)
        except Exception:
            continue
        for fx in fixtures:
            if fx["id"] in seen_events:
                continue  # kaksi PL-joukkuetta vastakkain: laske kerran
            seen_events.add(fx["id"])
            try:
                rows = event_minutes(fx["id"])
            except Exception:
                continue
            if not rows:
                continue
            events_used.append(fx)
            for r in rows:
                sofa_team = fx["home_id"] if r["side"] == "home" else fx["away_id"]
                # Vain PL-joukkueiden pelaajat: vastustaja voi olla mika tahansa.
                if sofa_team not in team_by_sofa:
                    continue
                pm = agg.get(r["sofascore_id"])
                if pm is None:
                    pm = PlayerMinutes(
                        sofascore_id=r["sofascore_id"],
                        name=r["name"],
                        team=team_by_sofa[sofa_team],
                        country=r.get("country", ""),
                    )
                    agg[r["sofascore_id"]] = pm
                pm.matches += 1
                pm.minutes += r["minutes"]
                pm.starts += 1 if r["started"] else 0
                pm.per_match.append(r["minutes"])

    # MM-LIPPU (Villen havainto 2.8): MM-kisoissa pitkalle paasseiden maiden
    # pelaajat eivat pelaa esikautta normaalisti. Finaali oli 19.7.2026 eli
    # kaksi viikkoa ennen tata ikkunaa. Naiden pelaajien matalat minuutit ovat
    # TURNAUSLEPOA, eivat merkki paikan menetyksesta. Ilman tata lippua
    # minuuttisignaali rankaisisi jarjestelmallisesti parhaita pelaajia
    # parhaista maista, eli olisi aktiivisesti haitallinen.
    wc_by_player = wc_players_by_last_appearance()
    wc_by_nation = wc_last_match_dates()
    import datetime as _dt
    today = _dt.date.fromtimestamp(now_ts)

    players = []
    for pm in agg.values():
        d = asdict(pm)
        d["avg_minutes"] = pm.avg_minutes
        d["start_rate"] = pm.start_rate
        # Ensisijaisesti pelaajataso (oikeasti pelasi MM-kisoissa). Jos
        # MM-haku epaonnistui kokonaan, EI palata kansalaisuuteen: se
        # yliliputtaisi. Silloin lippu jaa pois ja se nakyy metassa.
        last = wc_by_player.get(pm.sofascore_id)
        d["wc_played"] = last is not None
        d["wc_nation_last_match"] = wc_by_nation.get(pm.country)
        d["wc_last_match"] = last
        if last:
            d["wc_rest_days"] = (today - _dt.date.fromisoformat(last)).days
        else:
            d["wc_rest_days"] = None
        # MITTAUS 2.8: kaikilla 15 MM-pelaajalla oli TASAN 1 harjoitusottelu
        # (13-90 min), kun muilla oli 3-5 ottelua ja 190-226 min. Lepopaivat
        # (26-38) EIVAT erotelleet heita lainkaan, joten kynnys olisi
        # virheellisesti "puhdistanut" 14/15. Siksi lippu on osallistuminen,
        # ei lepoaika: MM-pelaajan minuutteja ei voi verrata muihin talla
        # esikaudella, piste.
        d["minutes_confounded"] = d["wc_played"]
        players.append(d)
    players.sort(key=lambda p: (-p["minutes"], p["name"]))
    flagged = sum(1 for p in players if p["minutes_confounded"])

    return {
        "meta": {
            "source": "sofascore",
            "generated_at": now_ts,
            "days_back": days_back,
            "events": len(events_used),
            "players": len(players),
            "wc_confounded": flagged,
            "wc_rest_days_threshold": WC_REST_DAYS,
            "wc_players_seen": len(wc_by_player),
            "note": (
                "Pre-season friendly minutes. Observation, not projection: "
                "rotation is heavy, opposition is uneven and trialists play. "
                "45 minutes in July does not mean 90 in August."
            ),
            "wc_note": (
                "minutes_confounded marks players who actually appeared at the "
                "2026 World Cup. Their friendly minutes are post-tournament "
                "ramp-up, not a loss of role, and are not comparable with "
                "players who had a normal summer. Any minutes signal must "
                "exclude them."
            ),
            "wc_absence_warning": (
                "The bigger confounder is absence, not low minutes. Players "
                "from the deepest runs have not appeared in a friendly at all, "
                "so a missing player is not a negative signal this pre-season."
            ),
        },
        "events": events_used,
        "players": players,
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--limit-teams", type=int, default=0, help="0 = kaikki")
    ap.add_argument("--out", default="data/preseason_minutes.json")
    a = ap.parse_args()

    teams = pl_teams()
    if a.limit_teams:
        teams = teams[: a.limit_teams]
    print(f"Joukkueita: {len(teams)}, ikkuna {a.days} vrk")

    def prog(i, n, short):
        print(f"  [{i}/{n}] {short}", flush=True)

    data = build(days_back=a.days, teams=teams, progress=prog)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    m = data["meta"]
    print(f"\nOtteluita: {m['events']} · pelaajia: {m['players']} -> {a.out}")
    for p in data["players"][:12]:
        print(f"  {p['name']:<24}{p['team']:<14}{p['matches']:>2} ott "
              f"{p['minutes']:>4} min  ka {p['avg_minutes']:>5}  aloitus {p['start_rate']}")


if __name__ == "__main__":
    main()
